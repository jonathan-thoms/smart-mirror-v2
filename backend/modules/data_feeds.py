"""
Smart Mirror — Data Feeds
Fetches live weather (OpenWeatherMap) and NIFTY 50 market data (yfinance).
"""

import asyncio
import logging
import requests
import yfinance as yf
from datetime import datetime
from backend.config import (
    OPENWEATHERMAP_API_KEY,
    WEATHER_CITY,
    WEATHER_COUNTRY_CODE,
    WEATHER_POLL_INTERVAL,
    NIFTY_SYMBOL,
    MARKET_POLL_INTERVAL,
)

logger = logging.getLogger(__name__)


# ─── Weather ────────────────────────────────────────────────────────────────

def fetch_weather() -> dict | None:
    """Fetch current weather from OpenWeatherMap API."""
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": f"{WEATHER_CITY},{WEATHER_COUNTRY_CODE}",
            "appid": OPENWEATHERMAP_API_KEY,
            "units": "metric",
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        return {
            "city": data["name"],
            "temp": round(data["main"]["temp"]),
            "feels_like": round(data["main"]["feels_like"]),
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"].title(),
            "icon": data["weather"][0]["icon"],
            "wind_speed": round(data["wind"]["speed"] * 3.6, 1),  # m/s → km/h
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Weather fetch failed: {e}")
        return None


# ─── Market Data ────────────────────────────────────────────────────────────

def fetch_nifty() -> dict | None:
    """Fetch NIFTY 50 index data from Yahoo Finance."""
    try:
        ticker = yf.Ticker(NIFTY_SYMBOL)
        info = ticker.info

        # Get current price and change
        current = info.get("regularMarketPrice") or info.get("previousClose", 0)
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose", 0)
        change = current - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0

        return {
            "symbol": "NIFTY 50",
            "price": round(current, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
            "prev_close": round(prev_close, 2),
            "day_high": round(info.get("dayHigh", 0), 2),
            "day_low": round(info.get("dayLow", 0), 2),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"NIFTY fetch failed: {e}")
        return None


# ─── Background Polling Tasks ───────────────────────────────────────────────

class DataFeedManager:
    """Manages periodic fetching of weather and market data."""

    def __init__(self):
        self.latest_weather: dict | None = None
        self.latest_market: dict | None = None
        self._weather_task: asyncio.Task | None = None
        self._market_task: asyncio.Task | None = None

    async def start(self):
        """Start background polling loops."""
        # Fetch immediately on start
        loop = asyncio.get_event_loop()
        self.latest_weather = await loop.run_in_executor(None, fetch_weather)
        self.latest_market = await loop.run_in_executor(None, fetch_nifty)

        self._weather_task = asyncio.create_task(self._poll_weather())
        self._market_task = asyncio.create_task(self._poll_market())
        logger.info("Data feed polling started")

    async def stop(self):
        """Cancel background polling."""
        for task in (self._weather_task, self._market_task):
            if task:
                task.cancel()
        logger.info("Data feed polling stopped")

    async def _poll_weather(self):
        while True:
            await asyncio.sleep(WEATHER_POLL_INTERVAL)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_weather)
            if result:
                self.latest_weather = result

    async def _poll_market(self):
        while True:
            await asyncio.sleep(MARKET_POLL_INTERVAL)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, fetch_nifty)
            if result:
                self.latest_market = result
