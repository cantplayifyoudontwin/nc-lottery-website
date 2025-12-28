"""
NC Lottery Website Generator - GitHub Actions Version
======================================================

This script generates a static HTML website with lottery analysis data.
It's designed to run on GitHub Actions and deploy to GitHub Pages.

Theme: Blue-purple gradient matching Instagram Reels content
"""

import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import os
import sys


def get_eastern_time():
    """Get current time in Eastern timezone"""
    utc_now = datetime.now(timezone.utc)
    eastern = utc_now - timedelta(hours=5)
    return eastern


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
    """Generate the complete HTML page with Instagram-matching theme"""
    
    eastern_now = get_eastern_time()
    update_time = eastern_now.strftime('%B %d, %Y at %I:%M %p') + ' EST'
    
    # Filter games by price
    high_price_games = [(g, b, t, d) for g, b, t, d in results if g.ticket_price >= 10]
    low_price_games = [(g, b, t, d) for g, b, t, d in results if g.ticket_price < 10]
    
    def generate_game_rows(games, limit=10, show_all=False):
        rows = ""
        display_games = games if show_all else games[:limit]
        for rank, (game, bottom_pct, top_pct, diff) in enumerate(display_games, 1):
            top_prize = game.get_top_prize()
            diff_class = "positive" if diff > 0 else "negative" if diff < 0 else "neutral"
            status_badge = f'<span class="badge reordered">Reordered</span>' if game.status == "Reordered" else ""
            
            # Format as "X of Y" for top prizes remaining
            top_remaining = f"{top_prize.remaining} of {top_prize.total}"
            
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
                    <td class="top-remaining">{top_remaining}</td>
                    <td class="diff {diff_class}">{diff:+.1f}%</td>
                </tr>
            """
        return rows
    
    def generate_most_top_prizes_rows(games, limit=10):
        """Generate rows for games ranked by most top prizes remaining (top prize >= $5000)"""
        # Filter for games with top prize >= $5000
        filtered_games = [(g, b, t, d) for g, b, t, d in games if g.get_top_prize().value >= 5000]
        
        # Sort by top prizes remaining (desc), then by differential (desc) as tiebreaker
        sorted_games = sorted(filtered_games, key=lambda x: (x[0].get_top_prize().remaining, x[3]), reverse=True)
        
        rows = ""
        display_games = sorted_games[:limit]
        for rank, (game, bottom_pct, top_pct, diff) in enumerate(display_games, 1):
            top_prize = game.get_top_prize()
            diff_class = "positive" if diff > 0 else "negative" if diff < 0 else "neutral"
            status_badge = f'<span class="badge reordered">Reordered</span>' if game.status == "Reordered" else ""
            
            top_remaining = f"{top_prize.remaining} of {top_prize.total}"
            
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
                    <td class="top-remaining highlight-remaining">{top_remaining}</td>
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
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            /* Blue-Purple gradient theme matching Instagram content */
            --gradient-start: #4A90D9;
            --gradient-end: #8B5CF6;
            --bg-primary: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #1a1a2e 100%);
            --bg-card: rgba(255, 255, 255, 0.08);
            --bg-card-hover: rgba(255, 255, 255, 0.12);
            --bg-glass: rgba(255, 255, 255, 0.05);
            --text-primary: #ffffff;
            --text-secondary: #c0c0d0;
            --text-muted: #8888a0;
            --accent-cyan: #00FFFF;
            --accent-gold: #FFD700;
            --accent-green: #00FF88;
            --accent-green-dim: rgba(0, 255, 136, 0.15);
            --accent-red: #FF6B6B;
            --accent-red-dim: rgba(255, 107, 107, 0.15);
            --border-color: rgba(255, 255, 255, 0.1);
            --shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Outfit', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            background-attachment: fixed;
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
            position: relative;
        }}
        
        /* Gradient overlay */
        body::before {{
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(180deg, 
                rgba(74, 144, 217, 0.1) 0%, 
                rgba(139, 92, 246, 0.1) 50%,
                rgba(74, 144, 217, 0.05) 100%);
            pointer-events: none;
            z-index: 0;
        }}
        
        /* Money tree watermark */
        body::after {{
            content: '$';
            position: fixed;
            bottom: 50px;
            right: 50px;
            font-size: 200px;
            font-weight: 800;
            color: rgba(255, 215, 0, 0.03);
            pointer-events: none;
            z-index: 0;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
            position: relative;
            z-index: 1;
        }}
        
        /* Header */
        header {{
            text-align: center;
            padding: 3rem 0;
            margin-bottom: 2rem;
        }}
        
        .logo {{
            font-size: 3rem;
            font-weight: 800;
            color: var(--accent-cyan);
            margin-bottom: 0.5rem;
            letter-spacing: -0.02em;
            text-shadow: 0 0 40px rgba(0, 255, 255, 0.3);
        }}
        
        .tagline {{
            color: var(--text-secondary);
            font-size: 1.2rem;
            font-weight: 400;
        }}
        
        .update-time {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 1.5rem;
            padding: 0.75rem 1.5rem;
            background: var(--bg-glass);
            backdrop-filter: blur(10px);
            border: 1px solid var(--border-color);
            border-radius: 2rem;
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .update-time::before {{
            content: '';
            width: 10px;
            height: 10px;
            background: var(--accent-green);
            border-radius: 50%;
            animation: pulse 2s infinite;
            box-shadow: 0 0 10px var(--accent-green);
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.5; transform: scale(0.9); }}
        }}
        
        /* Glass card style */
        .card {{
            background: var(--bg-card);
            backdrop-filter: blur(10px);
            border: 1px solid var(--border-color);
            border-radius: 1.5rem;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: var(--shadow);
        }}
        
        .card h3 {{
            color: var(--accent-cyan);
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .card p {{
            color: var(--text-secondary);
            font-size: 0.95rem;
            margin-bottom: 0.5rem;
        }}
        
        .card .highlight {{
            color: var(--text-primary);
            font-weight: 600;
        }}
        
        .card .positive {{ color: var(--accent-green); font-weight: 600; }}
        .card .negative {{ color: var(--accent-red); font-weight: 600; }}
        
        /* Disclaimer card */
        .disclaimer-card {{
            background: rgba(255, 107, 107, 0.1);
            border: 1px solid rgba(255, 107, 107, 0.3);
        }}
        
        .disclaimer-card h3 {{
            color: var(--accent-gold);
        }}
        
        .disclaimer-card .helpline {{
            color: var(--accent-cyan);
            font-weight: 600;
            font-family: 'JetBrains Mono', monospace;
        }}
        
        /* Section Headers */
        .section-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
        }}
        
        .section-title {{
            font-size: 1.4rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            color: var(--text-primary);
        }}
        
        .section-title .icon {{
            font-size: 1.5rem;
        }}
        
        .section-count {{
            background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
            padding: 0.35rem 1rem;
            border-radius: 1rem;
            font-size: 0.85rem;
            color: white;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
        }}
        
        /* Tables */
        .table-container {{
            background: var(--bg-card);
            backdrop-filter: blur(10px);
            border: 1px solid var(--border-color);
            border-radius: 1.5rem;
            overflow: hidden;
            margin-bottom: 2.5rem;
            box-shadow: var(--shadow);
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th {{
            background: rgba(0, 0, 0, 0.3);
            padding: 1rem;
            text-align: left;
            font-weight: 600;
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--accent-cyan);
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
            transition: all 0.3s ease;
        }}
        
        .game-row:hover {{
            background: var(--bg-card-hover);
            transform: translateX(4px);
        }}
        
        .rank {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
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
            padding: 0.2rem 0.6rem;
            border-radius: 0.5rem;
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            margin-left: 0.5rem;
        }}
        
        .badge.reordered {{
            background: linear-gradient(135deg, var(--gradient-start), var(--gradient-end));
            color: white;
        }}
        
        .price {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
            color: var(--accent-gold);
        }}
        
        .top-prize {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 500;
            color: var(--text-primary);
        }}
        
        .top-pct, .top-remaining {{
            font-family: 'JetBrains Mono', monospace;
            color: var(--text-secondary);
        }}
        
        .highlight-remaining {{
            color: var(--accent-gold) !important;
            font-weight: 600;
        }}
        
        .diff {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 700;
            text-align: right;
            padding: 0.5rem 0.75rem;
            border-radius: 0.5rem;
        }}
        
        .diff.positive {{
            color: var(--accent-green);
            background: var(--accent-green-dim);
            text-shadow: 0 0 10px rgba(0, 255, 136, 0.5);
        }}
        
        .diff.negative {{
            color: var(--accent-red);
            background: var(--accent-red-dim);
        }}
        
        .diff.neutral {{
            color: var(--text-muted);
        }}
        
        /* Footer */
        footer {{
            text-align: center;
            padding: 2rem 0;
            margin-top: 2rem;
        }}
        
        footer p {{
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
        }}
        
        footer a {{
            color: var(--accent-cyan);
            text-decoration: none;
            transition: color 0.3s ease;
        }}
        
        footer a:hover {{
            color: var(--accent-gold);
            text-decoration: underline;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            .container {{
                padding: 1rem;
            }}
            
            .logo {{
                font-size: 2rem;
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
            
            body::after {{
                font-size: 100px;
                bottom: 20px;
                right: 20px;
            }}
        }}
        
        @media (max-width: 500px) {{
            .top-remaining, th:nth-child(5) {{
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
        
        <div class="card">
            <h3>&#128202; How This Works</h3>
            <p><span class="highlight">Understanding the Differential</span></p>
            <p>The percentage of bottom prizes remaining gives us a fair estimate of how much of a game has been played through. For example, if 60% of bottom prizes remain, roughly 40% of tickets have been sold.</p>
            <p>The <span class="highlight">differential</span> compares the top prize percentage to the bottom prize percentage. When more top prizes remain proportionally than bottom prizes (a <span class="positive">positive differential</span>), each ticket you buy has a higher expected value than a game where the top prizes have already been claimed.</p>
            <p><span class="highlight">Example:</span> If a game has 80% of top prizes remaining but only 50% of bottom prizes remaining, the differential is +30%. This suggests the big prizes are still out there waiting to be won.</p>
            <p style="margin-top: 0.75rem; font-style: italic; color: var(--text-muted);">Click any row to view full prize details on the NC Lottery website.</p>
        </div>
        
        <div class="card disclaimer-card">
            <h3>&#9888; Important Disclaimer</h3>
            <p><span class="highlight">This is not financial advice.</span> Lottery games are forms of gambling and are inherently risky. A positive differential does not guarantee wins — every ticket is still a game of chance. Past results do not predict future outcomes. Only play with money you can afford to lose.</p>
            <p style="margin-top: 0.75rem;"><span class="highlight">If you or someone you know has a gambling problem, help is available.</span></p>
            <p>Call or text the National Problem Gambling Helpline: <span class="helpline">1-800-522-4700</span> (available 24/7, free and confidential).</p>
        </div>
        
        <section>
            <div class="section-header">
                <h2 class="section-title"><span class="icon">&#128176;</span> Top 10 Games $10 and Up</h2>
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
                            <th class="top-remaining">Top Left</th>
                            <th style="text-align: right;">Diff</th>
                        </tr>
                    </thead>
                    <tbody>
                        {generate_game_rows(high_price_games, limit=10)}
                    </tbody>
                </table>
            </div>
        </section>
        
        <section>
            <div class="section-header">
                <h2 class="section-title"><span class="icon">&#127915;</span> Top 10 Games Under $10</h2>
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
                            <th class="top-remaining">Top Left</th>
                            <th style="text-align: right;">Diff</th>
                        </tr>
                    </thead>
                    <tbody>
                        {generate_game_rows(low_price_games, limit=10)}
                    </tbody>
                </table>
            </div>
        </section>
        
        <section>
            <div class="section-header">
                <h2 class="section-title"><span class="icon">&#127942;</span> Most Top Prizes Remaining ($5K+)</h2>
                <span class="section-count">all prices</span>
            </div>
            <p style="color: var(--text-secondary); margin-bottom: 1rem; font-size: 0.9rem;">Games with top prizes of $5,000 or more, ranked by the number of top prizes still available. Differential is used as a tiebreaker.</p>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Game</th>
                            <th>Price</th>
                            <th>Top Prize</th>
                            <th class="top-remaining">Top Left</th>
                            <th style="text-align: right;">Diff</th>
                        </tr>
                    </thead>
                    <tbody>
                        {generate_most_top_prizes_rows(results, limit=10)}
                    </tbody>
                </table>
            </div>
        </section>
        
        <footer>
            <p>Data sourced from <a href="https://nclottery.com/scratch-off-prizes-remaining" target="_blank">NC Education Lottery</a></p>
            <p>Updated automatically every day at ~7-8 AM Eastern</p>
            <p style="margin-top: 1rem; font-size: 0.75rem;">Play responsibly. Must be 18+ to play.</p>
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
    
    eastern_now = get_eastern_time()
    print(f"Started at: {eastern_now.strftime('%Y-%m-%d %H:%M:%S')} Eastern")
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
    print(f"\nFinished at: {get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')} Eastern")


if __name__ == "__main__":
    main()
