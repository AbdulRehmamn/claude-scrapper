# TheBlueBook.com Scraper

Extracts Name, Phone, and Email from thebluebook.com listing/search pages,
auto-following pagination until no "next page" is found.

## Setup
1. Install Python 3.9+ and Google Chrome (needed for Selenium fallback on JS pages).
2. Double-click `start.bat` — it installs all dependencies and runs the scraper.
3. When prompted, paste the thebluebook.com search results URL you want to scrape.
4. Results are saved to `results.csv` in the same folder.

## Manual run
    pip install -r requirements.txt
    python scraper.py --url "https://www.thebluebook.com/..." --output results.csv

## Notes
- The scraper tries plain HTTP requests first and automatically switches to
  a headless Chrome browser (Selenium) if the page appears JavaScript-rendered.
- Review thebluebook.com's Terms of Service / robots.txt before scraping,
  use reasonable delays, and only use collected data lawfully (e.g., CAN-SPAM
  compliance if used for email outreach).