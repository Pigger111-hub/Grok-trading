# Product

## Register

product

## Users

One person, the owner of this repository, who checks the paper-trading dashboard every day, mostly on a phone. They are new to trading. They want to see, in a few seconds, how each simulated strategy's 10,000-dollar book is doing for Bitcoin and Ethereum, what changed since the last check, and how each one compares with simply buying and holding. All copy is in plain Thai.

## Product Purpose

A research lab that tests well-known trading rules on BTC and ETH, then runs the chosen ones forward on simulated money (a paper book) every four hours through GitHub Actions. The dashboard on GitHub Pages shows that paper book. Nothing places real orders. Success means the owner understands where each strategy stands without reading tables, trusts the numbers, and is never nudged toward trading real money before the evidence is there.

## Brand Personality

Lively, encouraging, honest. The feel of a workout app's daily summary (Strava, Apple Fitness): progress you can see at a glance, big confident numbers, a little motion when something changes. The fun comes from watching the race, never from hiding a loss.

## Anti-references

- Formal bank or brokerage websites: stiff, grey, form-heavy, boring.
- Crypto exchange UIs: black screens with neon green, flashing tickers, buy/sell buttons that invite impulse trades.
- Gambling or slot-machine aesthetics: confetti for wins, streak pressure, anything that frames risk as a game to chase.
- Purple-to-blue gradient startup heroes.

## Design Principles

1. Honest numbers first. A loss always reads as a loss: sign, arrow and word, never color alone, never softened by decoration.
2. Show what changed. Opening the page should answer "what happened since I last looked" before anything else.
3. Progress, not prompts. Motion and color celebrate movement in the simulation; nothing on the page asks the reader to act on a market.
4. Plain Thai for a beginner. Every term has a one-tap explanation; jargon sits behind it, not in front of it.
5. Same data, same truth. The page only re-presents `docs/data/dashboard.json`; it never invents new math the Python side doesn't produce.

## Accessibility & Inclusion

WCAG 2.1 AA. Body text at least 16px, contrast at least 4.5:1. Gains and losses carry a sign and an arrow as well as color. All motion respects `prefers-reduced-motion`. Charts have text equivalents in the standings above them.
