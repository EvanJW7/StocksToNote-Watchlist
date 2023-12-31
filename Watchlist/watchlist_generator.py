import asyncio
import yfinance as yf
import requests
from bs4 import BeautifulSoup
import stocks_list
import logging
import warnings
import numpy as np
from datetime import datetime, timedelta

logging.basicConfig(
    filename='watchlist.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(message)s - line %(lineno)d',
    datefmt='%Y-%m-%d %I:%M:%S %p'
)
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore", category=RuntimeWarning, message="divide by zero")


class DataCollector:
    def get_market_cap(stock):
        try:
            url = f'https://www.marketwatch.com/investing/stock/{stock}?mod=search_symbol'
            res = requests.get(url)
            soup = BeautifulSoup(res.text, 'lxml')
            mc = soup.findAll('li', class_='kv__item')[3]
            mc = mc.text[11:].strip()
            return mc
        except Exception as e:
            logger.error(f"Unexpected error on get_market_cap request for {stock}: {e}")
            return "No data"
        
    def get_short_float(stock):
        try:
            url = f'https://www.marketwatch.com/investing/stock/{stock}?mod=search_symbol'
            res = requests.get(url)
            soup = BeautifulSoup(res.text, 'lxml')
            sf = soup.findAll('li', class_='kv__item')[14]
            sf = sf.text[19:].strip()
            return sf
        except Exception as e:
            logger.error(f"Unexpected error on get_short_float request for {stock}: {e}")
            return "No data"
        
    def get_sector(stock):
        try:
            url = f'https://www.marketwatch.com/investing/stock/{stock}/company-profile?mod=mw_quote_tab'
            res = requests.get(url)
            soup = BeautifulSoup(res.content, 'lxml')
            industry = soup.findAll('span', class_="primary")[6].text
            sector = soup.findAll('span', class_="primary")[7].text
            if len(industry) <= len(sector):
                return industry
            else:
                return sector
        except Exception as e:
            logger.error(f"Unexpected error on get_sector request for {stock}: {e}")
            return "N/A"
    
    def get_current_price(stock):
        try:
            url = f'https://www.marketwatch.com/investing/stock/{stock}?mod=search_symbol'
            res = requests.get(url)
            soup = BeautifulSoup(res.text, 'lxml')
            cp = soup.findAll('td', class_ = "table__cell u-semi")[0].text
            cp = float(cp[1:])
            logger.info(f"Close price of {stock}: {cp}")
            return cp
        except Exception as e:
            logger.critical(f"Unexpected error on get_current_price request for {stock}: {e}")
            return 999
    
    def get_evidence_of_selling(start_date, stock):
        try:
            timestamp = datetime.strptime(str(start_date), "%Y-%m-%d %H:%M:%S%z")
            start_date_formatted = timestamp.strftime("%Y-%m-%d")
            input_date = datetime.strptime(start_date_formatted, "%Y-%m-%d")
            next_day = input_date + timedelta(days=1)
            end_date = next_day.strftime("%Y-%m-%d")
            df = yf.download(stock, start=start_date_formatted, end=end_date, interval='1m', progress=False)
            '''Exclude the first bar because yfinance includes the sum of premarket volume for the first candle,
            and exclude the last bar because it is often MOC selling that with an ambiguous candle'''
            df = df[1:-1]
            evidence_of_selling = "No"
            highest_volume_row = df[df['Volume'] == df['Volume'].max()]
            if highest_volume_row['Open'].values[0] >= highest_volume_row['Close'].values[0]:
                evidence_of_selling = "Yes"
            return evidence_of_selling
        except Exception as e:
            logger.error(f"Unexpected error on get_evidence_of_selling request for {stock}: {e}")
            return "No data"
        
    def calculate_volatility(closing_prices, stock):
        try:
            log_returns = [np.log(closing_prices[i] / closing_prices[i - 1]) for i in range(1, len(closing_prices))]
            avg_return = np.mean(log_returns)
            squared_deviations = [(log_return - avg_return) ** 2 for log_return in log_returns]
            variance = np.mean(squared_deviations)
            historical_volatility = np.sqrt(variance)
            vol = round(historical_volatility * np.sqrt(252) * 100, 2)
            return vol
        except Exception as e:
            logger.error(f"Unexpected error on calculate_volatility request for {stock}: {e}")
            return "No data"
        
class Watchlist:
    def __init__(self):
        self.data_processor = DataCollector()
        self.stocks = stocks_list.stocks
        self.stocks_in_play = 0
        self.sizzlers = []

    def closest_number(self, close, high, low, stock):
        try:
            dist1 = abs(close - high)
            dist2 = abs(close - low)
            if dist1 < dist2:
                return True
            else:
                return False
        except Exception as e:
            logger.critical(f"Unexpected error on closest_number calculation for {stock}: {e}")
            return True
        
    #Get yahoo finance stock data and screen for unusually bullish stocks along with their data
    async def get_stock_data(self, stock, i):
        try:
            ticker = yf.Ticker(stock)
            p = str(i) + 'd'
            stock_data = await asyncio.to_thread(ticker.history, period=p)
            stock_data = stock_data.reset_index()
            if len(stock_data) < 50:
                logger.warning("Not enough candlestick data for {stock}: length is {len(stock_data)}")
            #Since we are grabbing 50 days of data, [49] is the most recent day and [48] is the day before, etc.
            gap = (stock_data['Open'][49] - stock_data['High'][48]) / stock_data['High'][48] * 100
            green_initial_day = stock_data['Close'][49] > stock_data['Open'][49]
            avg_vol = stock_data['Volume'][0:49].mean()
            equity_vol = stock_data['Close'][0:49].mean() * stock_data['Volume'][0:49].median()
            vol_ratio = stock_data['Volume'][49] / avg_vol
            #If stock passes screen, fetch data for it and print
            if green_initial_day and round(gap) >= 2 and equity_vol >= 250000 and round(vol_ratio) > 3:
                date = stock_data['Date'][49]
                mc = DataCollector.get_market_cap(stock)
                sf = DataCollector.get_short_float(stock)
                sector = DataCollector.get_sector(stock)
                current_price = DataCollector.get_current_price(stock)
                evidence_of_selling = DataCollector.get_evidence_of_selling(date, stock)
                vol = DataCollector.calculate_volatility(stock_data['Close'][0:49], stock)
                momentum = self.closest_number(current_price, stock_data['High'][49], stock_data['Low'][49], stock)
                if momentum and evidence_of_selling == "No":
                    print(
                        f"{stock:>5}{date.strftime('%m/%d/%Y'):>14}{sector:^30}{mc:>8}{format(round(equity_vol), ','):>15}"
                        f"{round(gap, 2):>11}%{round(vol_ratio, 2):>11}{sf:>12}{vol:>13}%{evidence_of_selling:>14}")
                    self.stocks_in_play += 1
                    if vol > 100 and stock not in self.sizzlers:
                        self.sizzlers.append(stock)
        except KeyError:
            logger.warning(f"KeyError on get_stock_data request for {stock}")
        except IndexError:
            logger.warning(f"IndexError get_stock_data request code block for {stock}")

    async def main(self):
        tasks = []
        print("\n Stock      Date               Sector            MarketCap     EquityVol        Gap      VolRatio   "
              "ShortFloat   Volatility  EvidenceofSelling")
        #Grab 50 days of stock data and stop after doing after we do so for the previous 10 days
        for i in range(50, 60):
            print(
                f'{i}-------------------------------------------------------------------------------------'
                f'-------------------------------------------------------')
            for stock in self.stocks:
                tasks.append(asyncio.create_task(self.get_stock_data(stock, i)))
            await asyncio.gather(*tasks)
            tasks.clear()
        print(f"\nStocks in play: {self.stocks_in_play}")
        print(f"Sizzlers: {len(self.sizzlers)}\n")


if __name__ == '__main__':
    my_watchlist = Watchlist()
    asyncio.run(my_watchlist.main())
    








