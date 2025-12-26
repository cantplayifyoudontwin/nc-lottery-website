"""
NC Lottery Website Generator - GitHub Actions Version
======================================================

This script generates a static HTML website with lottery analysis data.
It's designed to run on GitHub Actions and deploy to GitHub Pages.

The website is automatically updated daily and hosted for free.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import os
import sys


@dataclass
class PrizeTier:
    """Represents a single prize tier"""
    value: float
    total: int
    remaining: int
    
    @property
    def percent_remaining(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.remaining / self.total) * 100


@dataclass
class GameData:
    """Data structure for a scratch-off game"""
    game_number: str
    game_name: str
    ticket_price: float
    url: str
    status: str = ""
    prize_tiers: List[PrizeTier] = field(default_factory=list)
    
    def get_top_prize(self) -> Optional[PrizeTier]:
        if not self.prize_tiers:
            return None
        return max(self.prize_tiers, key=lambda x: x.value)
    
    def get_bottom_prize(self) -> Optional[PrizeTier]:
        if not self.prize_tiers:
            return None
        return min(self.prize_tiers, key=lambda x: x.value)
    
    def calculate_differential(self) -> Tuple[float, float, float]:
        top = self.get_top_prize()
        bottom = self.get_bottom_prize()
        
        if not top or not bottom:
            return 0.0, 0.0, 0.0
        
        top_pct = top.percent_remaining
        bottom_pct = bottom.percent_remaining
        differential = top_pct - bottom_pct
        
        return bottom_pct, top_pct, differential


class NCLotteryAnalyzer:
    """Analyzes NC Lottery scratch-off games"""
    
    BASE_URL = "https://nclottery.com"
    PRIZES_URL = f"{BASE_URL}/scratch-off-prizes-remaining"
    GAMES_ENDING_URL = f"{BASE_URL}/scratch-off-games-ending"
    
    def __init__(self, delay_seconds: float = 1.0, verbose: bool = True):
        self.delay = delay_seconds
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        self.games_in_claims = set()
    
    def log(self, message: str):
        if self.verbose:
            print(message)
    
    def fetch_page(self, url: str) -> Optional[str]:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                self.log(f"  Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.delay * 2)
        return None
    
    def parse_prize_value(self, prize_str: str) -> float:
        cleaned = prize_str.replace('$', '').replace(',', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def parse_number(self, num_str: str) -> int:
        cleaned = num_str.replace(',', '').strip()
        try:
            return int(cleaned)
        except ValueError:
            return 0
    
    def get_games_in_claims_period(self) -> set:
        self.log("Checking for games in claims period...")
        html = self.fetch_page(self.GAMES_ENDING_URL)
        if not html:
            return set()
        
        soup = BeautifulSoup(html, 'html.parser')
        claims_games = set()
        today = datetime.now()
        
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    try:
                        game_num = cells[0].get_text(strip=True)
                        end_date_str = cells[3].get_text(strip=True)
                        claim_date_str = cells[4].get_text(strip=True)
                        
                        try:
                            end_date = datetime.strptime(end_date_str, '%b %d, %Y')
                            claim_date = datetime.strptime(claim_date_str, '%b %d, %Y')
                            
                            if end_date < today <= claim_date:
                                claims_games.add(game_num)
                        except ValueError:
                            pass
                    except (IndexError, AttributeError):
                        continue
        
        return claims_games
    
    def get_ticket_price_from_game_page(self, game_url: str) -> float:
        time.sleep(self.delay)
        
        html = self.fetch_page(game_url)
        if not html:
            return 0.0
        
        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text()
        
        price_match = re.search(r'Ticket\s*Price\s*\$(\d+)', page_text, re.IGNORECASE)
        if price_match:
            return float(price_match.group(1))
        
        for element in soup.find_all(['div', 'span', 'p', 'td']):
            text = element.get_text(strip=True)
            if 'Ticket Price' in text:
                price_match = re.search(r'\$(\d+)', text)
                if price_match:
                    return float(price_match.group(1))
        
        return 0.0
    
    def parse_game_section(self, game_table) -> Optional[GameData]:
        try:
            rows = game_table.find_all('tr')
            if len(rows) < 2:
                return None
            
            header_row = rows[0]
            game_link = header_row.find('a', href=re.compile(r'/scratch-off/\d+/'))
            if not game_link:
                return None
            
            href = game_link['href']
            game_name = game_link.get_text(strip=True)
            
            game_num_match = re.search(r'/scratch-off/(\d+)/', href)
            if not game_num_match:
                return None
            game_number = game_num_match.group(1)
            
            header_text = header_row.get_text()
            num_in_text = re.search(r'Game\s*Number:\s*(\d+)', header_text)
            if num_in_text:
                game_number = num_in_text.group(1)
            
            status = "Reordered" if "Reordered" in header_text else ""
            game_url = self.BASE_URL + href
            
            prize_tiers = []
            for row in rows[1:]:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    try:
                        value_text = cells[0].get_text(strip=True)
                        if not value_text.startswith('$'):
                            continue
                        
                        prize_value = self.parse_prize_value(value_text)
                        if prize_value <= 0:
                            continue
                        
                        total = self.parse_number(cells[2].get_text(strip=True))
                        remaining = self.parse_number(cells[3].get_text(strip=True))
                        
                        if total > 0:
                            prize_tiers.append(PrizeTier(
                                value=prize_value,
                                total=total,
                                remaining=remaining
                            ))
                    except (IndexError, ValueError):
                        continue
            
            if not prize_tiers:
                return None
            
            return GameData(
                game_number=game_number,
                game_name=game_name,
                ticket_price=0.0,
                url=game_url,
                status=status,
                prize_tiers=prize_tiers
            )
            
        except Exception as e:
            return None
    
    def scrape_active_games(self) -> List[GameData]:
        self.games_in_claims = self.get_games_in_claims_period()
        
        self.log("\nFetching prizes remaining page...")
        html = self.fetch_page(self.PRIZES_URL)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        games = []
        all_tables = soup.find_all('table')
        
        self.log(f"Found {len(all_tables)} tables to analyze...")
        
        processed_games = set()
        
        for table in all_tables:
            game_link = table.find('a', href=re.compile(r'/scratch-off/\d+/'))
            if not game_link:
                continue
            
            href = game_link['href']
            game_num_match = re.search(r'/scratch-off/(\d+)/', href)
            if not game_num_match:
                continue
            
            game_number = game_num_match.group(1)
            
            if game_number in processed_games:
                continue
            
            if game_number in self.games_in_claims:
                self.log(f"Skipping Game #{game_number} - in claims period")
                processed_games.add(game_number)
                continue
            
            game_data = self.parse_game_section(table)
            
            if game_data:
                processed_games.add(game_number)
                self.log(f"Processing Game #{game_data.game_number}: {game_data.game_name}")
                
                game_data.ticket_price = self.get_ticket_price_from_game_page(game_data.url)
                
                if game_data.ticket_price > 0:
                    self.log(f"  Price: ${game_data.ticket_price:.0f}, Tiers: {len(game_data.prize_tiers)}")
                    games.append(game_data)
        
        return games
    
    def analyze_and_rank_games(self) -> List[Tuple[GameData, float, float, float]]:
        games = self.scrape_active_games()
        
        if not games:
            return []
        
        self.log(f"\nProcessed {len(games)} active games")
        
        results = []
        for game in games:
            bottom_pct, top_pct, differential = game.calculate_differential()
            results.append((game, bottom_pct, top_pct, differential))
        
        results.sort(key=lambda x: x[3], reverse=True)
        return results


def format_price(price: float) -> str:
    if price == int(price):
        return f"${int(price)}"
    return f"${price:.2f}"


def format_prize(value: float) -> str:
    if value >= 1000000:
        return f"${value/1000000:.1f}M"
    elif value >= 1000:
        return f"${value/1000:.0f}K"
    else:
        return f"${value:.0f}"


def generate_html(results: List[Tuple[GameData, float, float, float]]) -> str:
    """Generate the complete HTML page"""
    
    now = datetime.now()
    update_time = now.strftime('%B %d, %Y at %I:%M %p') + ' UTC'
    
    # Filter games by price
    high_price_games = [(g, b, t, d) for g, b, t, d in results if g.ticket_price >= 10]
    low_price_games = [(g, b, t, d) for g, b, t, d in results if g.ticket_price < 10]
    
    def generate_game_rows(games, limit=10):
        rows = ""
        display_games = games[:limit]
        for rank, (game, bottom_pct, top_pct, diff) in enumerate(display_games, 1):
            top_prize = game.get_top_prize()
            diff_class = "positive" if diff > 0 else "negative" if diff < 0 else "neutral"
            status_badge = f'<span class="badge reordered">Reordered</span>' if game.status == "Reordered" else ""
            
            rows += f"""
                <tr class="game-row" onclick="window.open('{game.url}', '_blank')">
                    <td class="rank">{rank}</td>
                    <td class="game-name">
                        {game.game_name}
                        {status_badge}
                        <span class="game-number">#{game.game_number}</span>
                    </td>
                    <td class="price">{format_price(game.ticket_price)}</td>
                    <td class="top-prize">{format_prize(top_prize.value)}</td>
                    <td class="top-pct">{top_pct:.1f}%</td>
                    <td class="diff {diff_class}">{diff:+.1f}%</td>
                </tr>
            """
        return rows
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NC Lottery Scratch-Off Analyzer</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a24;
            --bg-hover: #22222e;
            --text-primary: #f0f0f5;
            --text-secondary: #8888a0;
            --text-muted: #555566;
            --accent-green: #00d67d;
            --accent-green-dim: #00d67d22;
            --accent-red: #ff4757;
            --accent-red-dim: #ff475722;
            --accent-gold: #ffd700;
            --accent-blue: #4dabf7;
            --border-color: #2a2a3a;
            --gradient-1: linear-gradient(135deg, #00d67d 0%, #00b368 100%);
            --gradient-2: linear-gradient(135deg, #4dabf7 0%, #3b8ed6 100%);
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        /* Header */
        header {{
            text-align: center;
            padding: 3rem 0;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }}
        
        .logo {{
            font-size: 2.5rem;
            font-weight: 700;
            background: var(--gradient-1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
            letter-spacing: -0.02em;
        }}
        
        .tagline {{
            color: var(--text-secondary);
            font-size: 1.1rem;
            font-weight: 300;
        }}
        
        .update-time {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 1.5rem;
            padding: 0.5rem 1rem;
            background: var(--bg-secondary);
            border-radius: 2rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .update-time::before {{
            content: '';
            width: 8px;
            height: 8px;
            background: var(--accent-green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        /* Info Box */
        .info-box {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 1rem;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .info-box h3 {{
            color: var(--accent-blue);
            font-size: 1rem;
            font-weight: 600;
            margin-bottom: 0.75rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .info-box p {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
        }}
        
        .info-box .highlight {{
            color: var(--text-primary);
            font-weight: 500;
        }}
        
        .info-box .positive {{ color: var(--accent-green); }}
        .info-box .negative {{ color: var(--accent-red); }}
        
        /* Section Headers */
        .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .section-title {{
            font-size: 1.25rem;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        
        .section-title .icon {{
            font-size: 1.5rem;
        }}
        
        .section-count {{
            background: var(--bg-card);
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
        }}
        
        /* Tables */
        .table-container {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 1rem;
            overflow: hidden;
            margin-bottom: 2.5rem;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th {{
            background: var(--bg-card);
            padding: 1rem;
            text-align: left;
            font-weight: 500;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            border-bottom: 1px solid var(--border-color);
        }}
        
        td {{
            padding: 1rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
        }}
        
        tr:last-child td {{
            border-bottom: none;
        }}
        
        .game-row {{
            cursor: pointer;
            transition: background 0.2s ease;
        }}
        
        .game-row:hover {{
            background: var(--bg-hover);
        }}
        
        .rank {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
            color: var(--text-muted);
            width: 50px;
        }}
        
        .game-name {{
            font-weight: 500;
        }}
        
        .game-number {{
            display: block;
            font-size: 0.8rem;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
            margin-top: 0.25rem;
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.15rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.7rem;
            font-weight: 500;
            text-transform: uppercase;
            margin-left: 0.5rem;
        }}
        
        .badge.reordered {{
            background: var(--accent-blue);
            color: var(--bg-primary);
        }}
        
        .price {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
            color: var(--accent-gold);
        }}
        
        .top-prize {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
        }}
        
        .top-pct {{
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-secondary);
        }}
        
        .diff {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            text-align: right;
        }}
        
        .diff.positive {{
            color: var(--accent-green);
            background: var(--accent-green-dim);
            border-radius: 0.25rem;
            padding: 0.25rem 0.5rem;
        }}
        
        .diff.negative {{
            color: var(--accent-red);
            background: var(--accent-red-dim);
            border-radius: 0.25rem;
            padding: 0.25rem 0.5rem;
        }}
        
        .diff.neutral {{
            color: var(--text-muted);
        }}
        
        /* Footer */
        footer {{
            text-align: center;
            padding: 2rem 0;
            border-top: 1px solid var(--border-color);
            margin-top: 2rem;
        }}
        
        footer p {{
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }}
        
        footer a {{
            color: var(--accent-blue);
            text-decoration: none;
        }}
        
        footer a:hover {{
            text-decoration: underline;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            .container {{
                padding: 1rem;
            }}
            
            .logo {{
                font-size: 1.75rem;
            }}
            
            th, td {{
                padding: 0.75rem 0.5rem;
                font-size: 0.85rem;
            }}
            
            .game-number {{
                display: none;
            }}
            
            .section-header {{
                flex-direction: column;
                align-items: flex-start;
                gap: 0.5rem;
            }}
        }}
        
        /* Hide columns on very small screens */
        @media (max-width: 500px) {{
            .top-pct, th:nth-child(5) {{
                display: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1 class="logo">NC Lottery Analyzer</h1>
            <p class="tagline">Find scratch-offs with the best prize differentials</p>
            <div class="update-time">Last updated: {update_time}</div>
        </header>
        
        <div class="info-box">
            <h3>📊 How to Read This Data</h3>
            <p><span class="highlight">Differential</span> = Top Prize % Remaining − Bottom Prize % Remaining</p>
            <p><span class="positive">Positive (+)</span> = More top prizes remain proportionally — potentially better value</p>
            <p><span class="negative">Negative (−)</span> = Fewer top prizes remain — the best prizes may be gone</p>
            <p style="margin-top: 0.75rem; font-style: italic;">Click any row to view full prize details on the NC Lottery website.</p>
        </div>
        
        <section>
            <div class="section-header">
                <h2 class="section-title"><span class="icon">💰</span> Top 10 Games $10 and Up</h2>
                <span class="section-count">showing 10 of {len(high_price_games)}</span>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Game</th>
                            <th>Price</th>
                            <th>Top Prize</th>
                            <th class="top-pct">Top %</th>
                            <th style="text-align: right;">Diff</th>
                        </tr>
                    </thead>
                    <tbody>
                        {generate_game_rows(high_price_games)}
                    </tbody>
                </table>
            </div>
        </section>
        
        <section>
            <div class="section-header">
                <h2 class="section-title"><span class="icon">🎫</span> Top 10 Games Under $10</h2>
                <span class="section-count">showing 10 of {len(low_price_games)}</span>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Game</th>
                            <th>Price</th>
                            <th>Top Prize</th>
                            <th class="top-pct">Top %</th>
                            <th style="text-align: right;">Diff</th>
                        </tr>
                    </thead>
                    <tbody>
                        {generate_game_rows(low_price_games)}
                    </tbody>
                </table>
            </div>
        </section>
        
        <footer>
            <p>Data sourced from <a href="https://nclottery.com/scratch-off-prizes-remaining" target="_blank">NC Education Lottery</a></p>
            <p>Updated automatically every day. For informational purposes only.</p>
            <p style="margin-top: 1rem; font-size: 0.75rem;">Lottery games are games of chance. Please play responsibly.</p>
        </footer>
    </div>
</body>
</html>
"""
    
    return html


def main():
    """Main execution function"""
    print("=" * 60)
    print("NC Lottery Website Generator")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()
    
    # Run analysis
    analyzer = NCLotteryAnalyzer(delay_seconds=0.5, verbose=True)
    results = analyzer.analyze_and_rank_games()
    
    if not results:
        print("\nERROR: No games found!")
        sys.exit(1)
    
    print(f"\nAnalysis complete! Found {len(results)} games.")
    
    # Generate HTML
    print("\nGenerating website...")
    html = generate_html(results)
    
    # Write to file
    output_path = "index.html"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Website saved to: {output_path}")
    print(f"\nFinished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")


if __name__ == "__main__":
    main()
