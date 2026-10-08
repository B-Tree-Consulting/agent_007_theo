# Trader-app BFA — compiled specification for Theo

As-built contract of the Trading 212 host that Theo invokes. Source: `b-tree-trader-app` (`backend/src/theo/`), spoke spec `docs/specs/theo-trading212-bfa.md`. Tool version **1.0.0**. Host slug **`trader-app`**.

This document is for the digital employee. It does not define trading strategy. Strategy stays in this DE definition.

## Boundary

| Layer | Owner | This BFA |
| --- | --- | --- |
| When Theo runs | AyDEO platform | Does not schedule, poll, or self-invoke |
| What to buy, sell, or keep | This DE definition | Does not score sentiment or pick a side |
| Place / cancel / read the book | This BFA | Validates, stores intents, talks to Trading 212 |
| Large-trade approval | Manager in CMS attention | Returns `needs-superior-defer`; does not create the attention item |

There is **one** brokerage account. Whoever asks on an entitled case, Theo always trades that account.

## Account and book

- Broker: Trading 212 Invest (demo by default; live only when the host is switched).
- Account owner / manager: `roman@aydeo.ai` (DRIS `primary_de_manager`). Theo does not choose the approver.
- Currency: **CZK**. Order `quantity` is always **shares**, never crowns.
- Long only. No shorting, no pies, no day-trade ban (a same-day sell is allowed up to the long).
- At most **20** distinct names (open positions plus working buys of names not already held). Adding to a held name is not a new name.
- Buys must be on the whitelist. Sells may close a name that has left the list.
- Empty whitelist → every buy fails `whitelist_empty`.

Current whitelist (operator file `backend/config/theo_whitelist.txt`):

`COUR_US_EQ`, `CRM_US_EQ`, `IVV_EQ`, `NOW_US_EQ`, `PLTR_US_EQ`, `QQQ_EQ`, `VT_EQ`, `VTI_EQ`, `SNOW_US_EQ`, `SAP_US_EQ`, `NOVN_CH_EQ`, `SDZ_CH_EQ`.

Always call `get_whitelist` before a buy; do not assume this list is frozen.

## Before you can trade

Trade tools are `case_effect`. They work only while the bound case journey is **`in_progress`**. On `assigned`, reads work and every trade returns `journey_disallows_tool`. Start work with CMS `cms_start_case_work` (not a tool on this host), then trade.

Reads work regardless of journey.

## Money versus shares

If the user speaks in crowns, call `get_account_summary`, take `fx_czk_per_unit`, and convert to shares yourself. Sending a crown amount as `quantity` would over-buy. Check `cash_available_czk` in the same call before any buy.

CZK notional for the gate and the cash check:

`quantity × notional_price × fx_czk_per_unit`

| Order type | `notional_price` |
| --- | --- |
| market | last price |
| limit, stop_limit | `limit_price` |
| stop | `stop_price` |

Gate: **10 000 CZK** (`THEO_ATTENTION_NOTIONAL`). At or under → matching low-risk `place_*` tool (broker POST in that invoke). Above → matching `place_large_*` twin (nothing reaches T212 until the manager approves).

## How to ask, then invoke

1. If the user has not said **market / limit / stop / stop-limit**, ask in chat. Do **not** default to market. Do not invoke a place tool yet.
2. If they chose limit, stop, or stop-limit and have not given the required prices or `DAY` vs `GOOD_TILL_CANCEL`, ask. Do not invent a price.
3. Convert CZK to shares if needed. Compute notional vs 10 000 CZK.
4. Invoke **one** typed tool. Callers never send `order_type`. Missing required fields are HTTP **422** (nothing stored).
5. You do not mint an order id. The host stores one. Retrying the same tool on the same chat turn with the same payload does not double-send. If the order changed (including a price the user just gave), call the same tool again on that turn.

## Catalog

Every tool is `execute_context=de_autonomous`, version `1.0.0`.

### Reads (`query`, `risk=low`, `case_tool_class=read`)

| Tool | Inputs | Use |
| --- | --- | --- |
| `get_account_summary` | none | Cash available / invested / equity, plus today's CNB CZK rate. Convert crowns; check funds. |
| `get_portfolio` | none | Holdings with marks and CZK value. Not working orders. |
| `get_open_orders` | none | Working broker orders and `t212_order_id` for cancel. |
| `get_whitelist` | none | Permitted buy tickers, name cap, CZK gate, environment. |
| `get_title_research` | `ticker` (whitelist) | Free-tier quote, history, profile, metrics, news, earnings, macro, filings. Each block names its source. Empty = unavailable, not a sell signal. No recommendation. |
| `get_trade_intents` | optional `status`, `limit` (default 20, max 50) | Host-recorded orders on this case, including awaiting approval and failures. |

### Review (`action_factory`, `risk=low`, `case_support`)

| Tool | Inputs | Use |
| --- | --- | --- |
| `review_portfolio` | `include_research` (bool, default true) | One pack: holdings, working orders, open proposals, whitelist, FX, optional research. Writes a case comment. Does not analyse or place. |

### Place — at or under the gate (`action_factory`, `risk=low`, `case_effect`)

| Tool | T212 | Required inputs |
| --- | --- | --- |
| `place_market_equity_order` | `POST /equity/orders/market` | `ticker`, `side`, `quantity` |
| `place_limit_equity_order` | `POST /equity/orders/limit` | those + `limit_price` + `time_validity` |
| `place_stop_equity_order` | `POST /equity/orders/stop` | those + `stop_price` + `time_validity` |
| `place_stop_limit_equity_order` | `POST /equity/orders/stop_limit` | those + `stop_price` + `limit_price` + `time_validity` |

Optional on all place tools: `extended_hours` (default false).

`side` is `buy` or `sell`. Quantity is always positive; the host sends a negative quantity to T212 for sells.

**Stop-loss:** sell `place_stop_equity_order` or `place_stop_limit_equity_order` with `stop_price` **below** last price and quantity inside the open long. A buy stop needs `stop_price` **above** last. Wrong side → `stop_price_invalid`. Once T212 accepts it, the broker fills without Theo.

A place that succeeds is sent **immediately**. Tell the user it is placed. The host writes the case comment; do not duplicate it.

Over the gate the low-risk tool fails `approval_required` and names the matching `place_large_*` twin.

### Place — above the gate (`action_factory`, `risk=high`, `case_effect`)

| Tool | Same fields as | Extra |
| --- | --- | --- |
| `place_large_market_equity_order` | market | `rationale` (20–500 chars) |
| `place_large_limit_equity_order` | limit | `rationale` |
| `place_large_stop_equity_order` | stop | `rationale` |
| `place_large_stop_limit_equity_order` | stop-limit | `rationale` |

Config/DRIS must mint these at **high** risk.

Nothing reaches the broker on submit. Tell the user the order is **waiting for the manager**, not that it is done. Do not create or resolve approval, do not poll, do not call again to finish it. On approve, the platform confirms under Theo's identity at the market as it then stands. On reject, nothing is placed; do not resubmit without a new instruction.

At or under the gate these tools fail `below_approval_threshold` and name the matching low-risk tool.

One undecided large order per ticker (`duplicate_pending_ticker`).

### Cancel (`action_factory`, `risk=low`, `case_effect`)

| Tool | Inputs |
| --- | --- |
| `cancel_equity_order` | `t212_order_id` from `get_open_orders` or a prior place |

Only orders this BFA placed. App-placed orders fail `order_not_tracked`. Cancelling does not re-place.

## Tool descriptions (verbatim)

Use these as the semantic meaning of each catalog row.

**get_account_summary** — Read the Trading 212 account's cash available to trade, invested amount, and total equity, together with today's CNB CZK rate. Use this before any buy to check funds, and to convert a crown amount into a share count yourself. Returns no secrets.

**get_portfolio** — List the equity positions currently held on the account, each with quantity, average price, last price, CZK market value, and unrealised profit or loss. Use this to see what the book holds before deciding anything. Does not include working orders.

**get_open_orders** — List orders currently working at the broker but not yet filled, including the stop and limit prices and the broker order id needed to cancel one. Use this to avoid ordering the same thing twice and to find an order to cancel.

**get_whitelist** — List the tickers this account is permitted to buy, along with the maximum number of names the book may hold and the CZK notional above which a trade needs the manager's approval. Use this before proposing any buy. A ticker not on this list cannot be bought, however good it looks.

**get_title_research** — Gather free-tier market information about one whitelisted ticker: last price, price history, company profile, metrics, news, earnings, macro series, and regulatory filings, each tagged with the source that answered. Use this as input to your own judgement. It contains no recommendation and never says whether to trade.

**get_trade_intents** — List the orders this BFA has recorded for the current case, including which are awaiting the manager's approval and which failed and why. Use this to see whether a trade you proposed earlier has gone through before proposing it again.

**review_portfolio** — Produce one combined review pack for the account: holdings with current marks, working orders, open proposals, the whitelist, the CZK rate, and research per name, then record the review as a case comment. Use this at the start of a portfolio review instead of calling the individual read tools one by one. It gathers facts and leaves an audit trail; it does not analyse, recommend, or place anything.

**place_market_equity_order** — Place a market equity order on Trading 212 now at whatever the market gives, for a whitelisted ticker at a CZK value at or under the approval threshold. Need ticker, buy or sell, and share count. Do not use this for a priced order. If the user has not said market, ask; do not default to it. Convert crowns to shares with get_account_summary. The order is sent immediately and recorded as a case comment. It refuses an order worth more than the threshold (use place_large_market_equity_order), a buy off the whitelist or short of cash, a sell larger than the position, and a missing ticker, side, or quantity: ask rather than guessing.

**place_limit_equity_order** — Place a limit equity order on Trading 212 that trades only at limit_price or better, for a whitelisted ticker at a CZK value at or under the approval threshold. Need ticker, buy or sell, share count, limit price per share, and DAY or GOOD_TILL_CANCEL. Ask for any of those; do not invent a price. The order is sent immediately and recorded as a case comment. Over the threshold use place_large_limit_equity_order. It refuses a buy off the whitelist or short of cash, and a sell larger than the position.

**place_stop_equity_order** — Place a stop equity order on Trading 212 that becomes a market order once stop_price is reached, for a whitelisted ticker at a CZK value at or under the approval threshold. Need ticker, buy or sell, share count, trigger price, and DAY or GOOD_TILL_CANCEL. A sell stop-loss trigger must sit below the last price; a buy stop above it. Ask rather than inventing. The order is sent immediately. Over the threshold use place_large_stop_equity_order.

**place_stop_limit_equity_order** — Place a stop-limit equity order on Trading 212 that becomes a limit order at limit_price once stop_price is reached, for a whitelisted ticker at a CZK value at or under the approval threshold. Need ticker, buy or sell, share count, both prices, and DAY or GOOD_TILL_CANCEL. Ask rather than inventing. The order is sent immediately. Over the threshold use place_large_stop_limit_equity_order.

**place_large_market_equity_order** — Propose a market equity order worth more than the approval threshold and send it to your manager for approval. Need ticker, buy or sell, share count, and a rationale of at least 20 characters. Nothing reaches the broker when you call this. Tell the user their order is waiting for the manager, not that it is done. Do not watch for the approval or call anything again to complete it. At or under the threshold use place_market_equity_order instead.

**place_large_limit_equity_order** — Propose a limit equity order worth more than the approval threshold and send it to your manager for approval. Need ticker, buy or sell, share count, limit price, DAY or GOOD_TILL_CANCEL, and a rationale of at least 20 characters. Nothing reaches the broker. Tell the user it is waiting for the manager. At or under the threshold use place_limit_equity_order instead.

**place_large_stop_equity_order** — Propose a stop equity order worth more than the approval threshold and send it to your manager for approval. Need ticker, buy or sell, share count, trigger price, DAY or GOOD_TILL_CANCEL, and a rationale of at least 20 characters. Nothing reaches the broker. Tell the user it is waiting for the manager. At or under the threshold use place_stop_equity_order instead.

**place_large_stop_limit_equity_order** — Propose a stop-limit equity order worth more than the approval threshold and send it to your manager for approval. Need ticker, buy or sell, share count, stop price, limit price, DAY or GOOD_TILL_CANCEL, and a rationale of at least 20 characters. Nothing reaches the broker. Tell the user it is waiting for the manager. At or under the threshold use place_stop_limit_equity_order instead.

**cancel_equity_order** — Cancel one order that is still working at the broker and was placed through this BFA, and record the cancellation as a case comment. Use this to withdraw an order the user changed their mind about or that is no longer wanted. It cannot cancel an order placed in the Trading 212 app, cannot touch an order that already filled, and cancelling does not re-place anything.

## Operating context (host catalog)

The host also publishes this as `operating_context` on the catalog envelope. Treat it as the BFA manual.

```
WHAT THIS BFA IS
This BFA is your hands on one real brokerage account: a Trading 212 account owned by roman@aydeo.ai, holding Czech crowns. Through it you can read the account and place, propose, or cancel equity orders. It is not your brain. It does not decide what to buy or sell, it does not judge whether a price is good, and it does not decide when you run. Your digital-employee definition and the AyDEO platform decide those. Every tool here either reports a fact or carries out an instruction you have already decided on.

WHO IS INVOLVED
Any AyDEO user who can reach you on a case may ask you about the portfolio or ask you to trade. There is only one brokerage account and you always trade it, whoever asked. Trades above a CZK threshold are approved by your manager before they reach the broker. You never choose the approver and you never approve anything yourself.

BEFORE YOU CAN TRADE
The trading tools affect the case, so they work only while the bound case is in progress. If a trade is refused because the journey disallows the tool, the case work has not been started: start it, then trade. The read tools work regardless.

MONEY VERSUS SHARES
Every order is a number of shares, never an amount of money. If the user speaks in crowns, call get_account_summary, take the CZK rate it returns, and work out the share count yourself. Sending a crown amount as a quantity would buy a hundred times too much. Check available cash in the same call before any buy.

GETTING THE FACTS
For a full picture in one call use review_portfolio: holdings, working orders, open proposals, the whitelist, the rate, and research per name, and it records the review in the case. For single facts use get_portfolio for holdings, get_open_orders for orders still working at the broker, get_whitelist for what may be bought, get_title_research for information on one name, and get_trade_intents to see what you have already ordered or proposed on this case. Research is gathered from free sources and each answer names its source; treat a missing block as unavailable, not as bad news.

WHAT YOU MAY BUY
Only a ticker returned by get_whitelist, and the book holds at most 20 different names. A name already held may be added to without counting again. You may always sell a name you hold, even if it has left the whitelist. You cannot sell more than the account holds and you cannot sell short.

ORDER TYPES
There is one place tool per type. place_market_equity_order buys or sells at whatever the market gives. place_limit_equity_order trades only at your limit_price or better. place_stop_equity_order becomes a market order once the price reaches your stop_price. place_stop_limit_equity_order becomes a limit order at limit_price once stop_price is reached. Limit, stop, and stop-limit also need a validity: DAY expires at the end of today, GOOD_TILL_CANCEL rests until it fills or you cancel it. A stop-loss is a sell stop or stop-limit with a trigger below the current price: once Trading 212 accepts it, the broker sells automatically if the price falls that far, without you being involved.

ASK WHEN YOU DO NOT KNOW
If the user has not said which order type, ask them in the chat and do not invoke a place tool. If they chose limit, stop, or stop-limit and have not given the prices or DAY versus GOOD_TILL_CANCEL that type needs, ask them. Do not invent a price and do not default to market. Missing fields are rejected before the order is stored.

PLACING A TRADE
Work out the CZK value of the order first. At or under 10000 CZK call the matching low-risk tool: place_market_equity_order, place_limit_equity_order, place_stop_equity_order, or place_stop_limit_equity_order. It goes to the broker in that one call and you can tell the user it is placed. Above 10000 CZK call the matching place_large_* twin and include your rationale, because your manager reads it when deciding. Nothing reaches the broker on that call. Tell the user their order is waiting for the manager, not that it is done. Do not create or resolve the approval, do not watch for it, and do not call anything again to finish it: when the manager approves, the platform places the order for you under your own identity, at the market as it then stands. If the manager rejects it, nothing is placed; tell the user and do not submit the same trade again without new instruction.

REPEATING AND CORRECTING
You do not invent an id for an order. This BFA stores one. A retry of the same tool on the same chat turn repeats that order and does not send it twice. If the order itself changes before it has been sent, including when the user gives you a price you asked for, call the same tool again on that turn and the new order replaces the proposal. An order already sent, in flight, or cancelled is not replaced.

CANCELLING
cancel_equity_order withdraws an order still working at the broker, and only one this BFA placed. It cannot touch an order placed in the Trading 212 app or one that has already filled. Cancelling does not replace the order with anything.

THE CASE RECORD
These tools write their own case comments describing what they did. You do not pass comment text and you cannot change what they write. Do not duplicate a comment by hand, and do not assume one exists unless the tool reported it.

WHEN SOMETHING IS REFUSED
Every refusal comes back with a reason: off the whitelist, not enough cash, more than the position holds, too large without approval, no price available, stop on the wrong side of the market. Read it, tell the user plainly what stopped it, and fix the order or ask them. A refusal means nothing was traded.
```

## Refusals

| Code | Meaning |
| --- | --- |
| `validation_error` | Incomplete canonical payload or missing case |
| HTTP 422 | Missing schema-required field on a typed tool |
| `approval_required` | Used a low-risk place tool above 10 000 CZK |
| `below_approval_threshold` | Used a large tool at or under the gate |
| `whitelist_rejected` / `whitelist_empty` | Buy not permitted |
| `insufficient_cash` | Buy notional above free cash |
| `short_rejected` | Sell larger than the long minus working sells |
| `position_cap` | Would exceed 20 names |
| `stop_price_invalid` | Trigger on the wrong side of last |
| `quote_unavailable` / `fx_unavailable` | No last price or CNB fixing |
| `duplicate_pending_ticker` | Second large proposal for that ticker |
| `order_not_tracked` | Cancel of an order this host did not place |
| `broker_rejected` / `broker_ambiguous` | Trading 212 refused or several matching orders |
| `journey_disallows_tool` | Trade while case is not `in_progress` |
| `request_id_reused` | Same chat-turn correlation, different payload, after the order was already sent |

A refusal means **nothing was traded**. Tell the user the reason and fix or ask.

## Out of scope for this BFA

Shorting, pies, paid market data, a coded buy/sell/keep policy, multi-currency, an in-process scheduler, host-built attention items, and any loop that waits for approval. No 15-minute / 5% price-drift re-check. No initialization basket.

## Config/DRIS

Grant every catalog tool. Mint each `place_large_*_equity_order` at **high** risk. Old names `place_equity_order` and `place_large_equity_order` are removed and will 404.
