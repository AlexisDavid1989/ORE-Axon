# Field-map XPath samples (verbatim)

Captured by calling `UnifiedXPathProvider.get_xpath(domain, item_name)`
directly in Python, against `ORE_Forge`'s own virtualenv interpreter
(`ORE_Forge/.venv/Scripts/python.exe`), with `ORE_Forge` inserted onto
`sys.path` and no other change to the repo. Not routed through the
`ore-mapping` MCP server — see `docs/FIELDMAP-SOURCE.md` Step 1 for why
that route doesn't reach this method.

```python
import sys
sys.path.insert(0, r"C:\Users\Alexis\OneDrive\Documents\repos\ORE_Forge")
from scripts.xpath.unified_xpath_provider import UnifiedXPathProvider

provider = UnifiedXPathProvider()
nodes = provider.get_xpath("trade", "FX Forward")          # Trade_Type: FxForward
nodes = provider.get_xpath("trade", "Interest Rate Swap")  # Trade_Type: Swap
nodes = provider.get_xpath("trade", "Interest Rate Swaption")  # Trade_Type: Swaption
```

`provider.get_trade_types()` returned **177** names at the time of capture
(ORE_Forge commit `9367ff4`, see FIELDMAP-SOURCE.md Step 5). There is no
entry literally named `"Swap"` or `"Swaption"` — those are `Trade_Type`
values shared by several display-name entries (see FIELDMAP-SOURCE.md /
prior profile's Step 3 fan-in table). `"Interest Rate Swap"` and
`"Interest Rate Swaption"` are the representative entries whose
`Trade_Type` is exactly `Swap` / `Swaption`.

Each output line below is one node dict, one per line, `json.dumps`'d
verbatim, in the exact order `get_xpath` returned them. Nothing has been
reordered, filtered, or reformatted.

---

## FxForward — `get_xpath("trade", "FX Forward")` — 12 nodes

```json
{"xpath": "Trade", "tag": "Trade", "is_field": true, "value": "FxForward_001", "level": 0, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/TradeType", "tag": "TradeType", "is_field": true, "value": "FxForward", "level": 1, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/Envelope", "tag": "Envelope", "is_field": false, "value": null, "level": 1, "type": "container", "is_choice_based": false}
{"xpath": "Trade/Envelope/CounterParty", "tag": "CounterParty", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true}
{"xpath": "Trade/Envelope/NettingSetId", "tag": "NettingSetId", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true}
{"xpath": "Trade/FxForwardData", "tag": "FxForwardData", "is_field": false, "value": null, "level": 1, "type": "container", "is_choice_based": false}
{"xpath": "Trade/FxForwardData/BoughtCurrency", "tag": "BoughtCurrency", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "data_type": "Double", "risk_factor_type": "currency"}
{"xpath": "Trade/FxForwardData/BoughtAmount", "tag": "BoughtAmount", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Double"}
{"xpath": "Trade/FxForwardData/SoldCurrency", "tag": "SoldCurrency", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "data_type": "String", "risk_factor_type": "currency"}
{"xpath": "Trade/FxForwardData/SoldAmount", "tag": "SoldAmount", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Double"}
{"xpath": "Trade/FxForwardData/ValueDate", "tag": "ValueDate", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/FxForwardData/Settlement", "tag": "Settlement", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "SettlementType", "data_type": "String", "is_activatable": true}
```

Note: `BoughtCurrency`'s `data_type` is `"Double"` and `SoldCurrency`'s is
`"String"` for what are both currency codes — an inconsistency in the
source data itself, not introduced by the XPath builder (see
FIELDMAP-SOURCE.md Risks).

---

## Swap — `get_xpath("trade", "Interest Rate Swap")` — 84 nodes

```json
{"xpath": "Trade", "tag": "Trade", "is_field": true, "value": "Swap_001", "level": 0, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/TradeType", "tag": "TradeType", "is_field": true, "value": "Swap", "level": 1, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/Envelope", "tag": "Envelope", "is_field": false, "value": null, "level": 1, "type": "container", "is_choice_based": false}
{"xpath": "Trade/Envelope/CounterParty", "tag": "CounterParty", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true}
{"xpath": "Trade/Envelope/NettingSetId", "tag": "NettingSetId", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true}
{"xpath": "Trade/SwapData", "tag": "SwapData", "is_field": false, "value": null, "level": 1, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/Settlement", "tag": "Settlement", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "SettlementType", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[1]", "tag": "LegData[1]{Fixed}", "is_field": false, "value": null, "level": 2, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[1]/LegType", "tag": "LegType", "is_field": true, "value": "Fixed", "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/Payer", "tag": "Payer", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Payer", "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[1]/Currency", "tag": "Currency", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "data_type": "String", "risk_factor_type": "currency"}
{"xpath": "Trade/SwapData/LegData[1]/PaymentConvention", "tag": "PaymentConvention", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/DayCounter", "tag": "DayCounter", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DayCounter", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData", "tag": "ScheduleData{Rules}", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules", "tag": "Rules", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/StartDate", "tag": "StartDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/EndDate", "tag": "EndDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/Tenor", "tag": "Tenor", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/Calendar", "tag": "Calendar", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Calendar", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/Convention", "tag": "Convention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/TermConvention", "tag": "TermConvention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "BusinessDayConvention", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/Rule", "tag": "Rule", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DateGenerationRule", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/EndOfMonth", "tag": "EndOfMonth", "is_field": true, "value": "false", "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/FirstDate", "tag": "FirstDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[1]/ScheduleData/Rules/LastDate", "tag": "LastDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[1]/Notionals", "tag": "Notionals", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[1]/Notionals/Notional", "tag": "Notional", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[1]/Notionals/Exchanges", "tag": "Exchanges", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[1]/Notionals/Exchanges/NotionalInitialExchange", "tag": "NotionalInitialExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[1]/Notionals/Exchanges/NotionalFinalExchange", "tag": "NotionalFinalExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[1]/Notionals/Exchanges/NotionalAmortizingExchange", "tag": "NotionalAmortizingExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[1]/FixedLegData", "tag": "FixedLegData", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[1]/FixedLegData/Rates", "tag": "Rates", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwapData/LegData[1]/FixedLegData/Rates/Rate", "tag": "Rate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[2]", "tag": "LegData[2]{Floating}", "is_field": false, "value": null, "level": 2, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/LegType", "tag": "LegType", "is_field": true, "value": "Floating", "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/Payer", "tag": "Payer", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Payer", "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[2]/Currency", "tag": "Currency", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "data_type": "String", "risk_factor_type": "currency"}
{"xpath": "Trade/SwapData/LegData[2]/PaymentConvention", "tag": "PaymentConvention", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/DayCounter", "tag": "DayCounter", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DayCounter", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData", "tag": "ScheduleData{Rules}", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules", "tag": "Rules", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/StartDate", "tag": "StartDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/EndDate", "tag": "EndDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/Tenor", "tag": "Tenor", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/Calendar", "tag": "Calendar", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Calendar", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/Convention", "tag": "Convention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/TermConvention", "tag": "TermConvention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "BusinessDayConvention", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/Rule", "tag": "Rule", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DateGenerationRule", "data_type": "String"}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/EndOfMonth", "tag": "EndOfMonth", "is_field": true, "value": "false", "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/FirstDate", "tag": "FirstDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/ScheduleData/Rules/LastDate", "tag": "LastDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/Notionals", "tag": "Notionals", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/Notionals/Notional", "tag": "Notional", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[2]/Notionals/Exchanges", "tag": "Exchanges", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/Notionals/Exchanges/NotionalInitialExchange", "tag": "NotionalInitialExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[2]/Notionals/Exchanges/NotionalFinalExchange", "tag": "NotionalFinalExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[2]/Notionals/Exchanges/NotionalAmortizingExchange", "tag": "NotionalAmortizingExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData", "tag": "FloatingLegData", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Index", "tag": "Index", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "IRIndex", "data_type": "String", "risk_factor_type": "ir_index"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Spreads", "tag": "Spreads", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Spreads/Spread", "tag": "Spread", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/FixingDays", "tag": "FixingDays", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Integer"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/IsInArrears", "tag": "IsInArrears", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/LastRecentPeriod", "tag": "LastRecentPeriod", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/LastRecentPeriodCalendar", "tag": "LastRecentPeriodCalendar", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Lookback", "tag": "Lookback", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/RateCutoff", "tag": "RateCutoff", "is_field": true, "value": "0", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Integer", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/IsAveraged", "tag": "IsAveraged", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/HasSubPeriods", "tag": "HasSubPeriods", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/IncludeSpread", "tag": "IncludeSpread", "is_field": true, "value": "false", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/IsNotResettingXCCY", "tag": "IsNotResettingXCCY", "is_field": true, "value": "false", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Caps", "tag": "Caps", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Caps/Cap", "tag": "Cap", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Floors", "tag": "Floors", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Floors/Floor", "tag": "Floor", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Gearings", "tag": "Gearings", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/Gearings/Gearing", "tag": "Gearing", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/NakedOption", "tag": "NakedOption", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/LocalCapFloor", "tag": "LocalCapFloor", "is_field": true, "value": "false", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/FixingSchedule", "tag": "FixingSchedule", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/ResetSchedule", "tag": "ResetSchedule", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/HistoricalFixings", "tag": "HistoricalFixings", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwapData/LegData[2]/FloatingLegData/HistoricalFixings/Fixing", "tag": "Fixing", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Double"}
```

---

## Swaption — `get_xpath("trade", "Interest Rate Swaption")` — 113 nodes

```json
{"xpath": "Trade", "tag": "Trade", "is_field": true, "value": "Swaption_001", "level": 0, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/TradeType", "tag": "TradeType", "is_field": true, "value": "Swaption", "level": 1, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/Envelope", "tag": "Envelope", "is_field": false, "value": null, "level": 1, "type": "container", "is_choice_based": false}
{"xpath": "Trade/Envelope/CounterParty", "tag": "CounterParty", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true}
{"xpath": "Trade/Envelope/NettingSetId", "tag": "NettingSetId", "is_field": true, "value": null, "level": 2, "type": "field", "is_choice_based": false, "is_optional": true}
{"xpath": "Trade/SwaptionData", "tag": "SwaptionData", "is_field": false, "value": null, "level": 1, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/OptionData", "tag": "OptionData", "is_field": false, "value": null, "level": 2, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/OptionData/LongShort", "tag": "LongShort", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "LongShort", "data_type": "String"}
{"xpath": "Trade/SwaptionData/OptionData/OptionType", "tag": "OptionType", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "OptionType", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/Style", "tag": "Style", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "ExerciseStyle", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/Settlement", "tag": "Settlement", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "SettlementType", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseDates", "tag": "ExerciseDates", "is_field": false, "value": null, "level": 3, "type": "array"}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseDates/ExerciseDate", "tag": "ExerciseDate", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/OptionData/PayoffType", "tag": "PayoffType", "is_field": true, "value": "", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "PayoffType", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/PayoffType2", "tag": "PayoffType2", "is_field": true, "value": "Arithmetic", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "AveragingMethod", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/NoticePeriod", "tag": "NoticePeriod", "is_field": true, "value": "0D", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "PeriodDays", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/NoticeCalendar", "tag": "NoticeCalendar", "is_field": true, "value": "NullCalendar", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Calendar", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/NoticeConvention", "tag": "NoticeConvention", "is_field": true, "value": "Unadjusted", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "BusinessDayConvention", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/MidCouponExercise", "tag": "MidCouponExercise", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/SettlementMethod", "tag": "SettlementMethod", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "SettlementMethod", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/PayOffAtExpiry", "tag": "PayOffAtExpiry", "is_field": true, "value": "true", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/PremiumAmount", "tag": "PremiumAmount", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Double", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/PremiumCurrency", "tag": "PremiumCurrency", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Currency", "data_type": "String", "risk_factor_type": "currency", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/PremiumPayDate", "tag": "PremiumPayDate", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/Premiums", "tag": "Premiums", "is_field": false, "value": null, "level": 3, "type": "array"}
{"xpath": "Trade/SwaptionData/OptionData/Premiums/Premium", "tag": "Premium", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/OptionData/Premiums/Premium/Amount", "tag": "Amount", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Double"}
{"xpath": "Trade/SwaptionData/OptionData/Premiums/Premium/Currency", "tag": "Currency", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "risk_factor_type": "currency"}
{"xpath": "Trade/SwaptionData/OptionData/Premiums/Premium/PayDate", "tag": "PayDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/OptionData/ExercisePrices", "tag": "ExercisePrices", "is_field": true, "value": "1.0", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseFees", "tag": "ExerciseFees", "is_field": false, "value": null, "level": 3, "type": "array"}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseFees/ExerciseFee", "tag": "ExerciseFee", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Double"}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseFeeSettlementPeriod", "tag": "ExerciseFeeSettlementPeriod", "is_field": true, "value": "0D", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "PeriodDays", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseFeeSettlementCalendar", "tag": "ExerciseFeeSettlementCalendar", "is_field": true, "value": "NullCalendar", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Calendar", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/ExerciseFeeSettlementConvention", "tag": "ExerciseFeeSettlementConvention", "is_field": true, "value": "Unadjusted", "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "BusinessDayConvention", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/OptionData/AutomaticExercise", "tag": "AutomaticExercise", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[1]", "tag": "LegData[1]{Fixed}", "is_field": false, "value": null, "level": 2, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[1]/LegType", "tag": "LegType", "is_field": true, "value": "Fixed", "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/Payer", "tag": "Payer", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Payer", "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[1]/Currency", "tag": "Currency", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "data_type": "String", "risk_factor_type": "currency"}
{"xpath": "Trade/SwaptionData/LegData[1]/PaymentConvention", "tag": "PaymentConvention", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/DayCounter", "tag": "DayCounter", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DayCounter", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData", "tag": "ScheduleData{Rules}", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules", "tag": "Rules", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/StartDate", "tag": "StartDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/EndDate", "tag": "EndDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/Tenor", "tag": "Tenor", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/Calendar", "tag": "Calendar", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Calendar", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/Convention", "tag": "Convention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/TermConvention", "tag": "TermConvention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "BusinessDayConvention", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/Rule", "tag": "Rule", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DateGenerationRule", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/EndOfMonth", "tag": "EndOfMonth", "is_field": true, "value": "false", "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/FirstDate", "tag": "FirstDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[1]/ScheduleData/Rules/LastDate", "tag": "LastDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[1]/Notionals", "tag": "Notionals", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[1]/Notionals/Notional", "tag": "Notional", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[1]/Notionals/Exchanges", "tag": "Exchanges", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[1]/Notionals/Exchanges/NotionalInitialExchange", "tag": "NotionalInitialExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[1]/Notionals/Exchanges/NotionalFinalExchange", "tag": "NotionalFinalExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[1]/Notionals/Exchanges/NotionalAmortizingExchange", "tag": "NotionalAmortizingExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[1]/FixedLegData", "tag": "FixedLegData", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[1]/FixedLegData/Rates", "tag": "Rates", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwaptionData/LegData[1]/FixedLegData/Rates/Rate", "tag": "Rate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[2]", "tag": "LegData[2]{Floating}", "is_field": false, "value": null, "level": 2, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/LegType", "tag": "LegType", "is_field": true, "value": "Floating", "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/Payer", "tag": "Payer", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Payer", "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[2]/Currency", "tag": "Currency", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Currency", "data_type": "String", "risk_factor_type": "currency"}
{"xpath": "Trade/SwaptionData/LegData[2]/PaymentConvention", "tag": "PaymentConvention", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/DayCounter", "tag": "DayCounter", "is_field": true, "value": null, "level": 3, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DayCounter", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData", "tag": "ScheduleData{Rules}", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules", "tag": "Rules", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/StartDate", "tag": "StartDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/EndDate", "tag": "EndDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Date"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/Tenor", "tag": "Tenor", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/Calendar", "tag": "Calendar", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "Calendar", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/Convention", "tag": "Convention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "BusinessDayConvention", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/TermConvention", "tag": "TermConvention", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "BusinessDayConvention", "data_type": "String", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/Rule", "tag": "Rule", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "DateGenerationRule", "data_type": "String"}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/EndOfMonth", "tag": "EndOfMonth", "is_field": true, "value": "false", "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/FirstDate", "tag": "FirstDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/ScheduleData/Rules/LastDate", "tag": "LastDate", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Date", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/Notionals", "tag": "Notionals", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/Notionals/Notional", "tag": "Notional", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[2]/Notionals/Exchanges", "tag": "Exchanges", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/Notionals/Exchanges/NotionalInitialExchange", "tag": "NotionalInitialExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[2]/Notionals/Exchanges/NotionalFinalExchange", "tag": "NotionalFinalExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[2]/Notionals/Exchanges/NotionalAmortizingExchange", "tag": "NotionalAmortizingExchange", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Boolean"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData", "tag": "FloatingLegData", "is_field": false, "value": null, "level": 3, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Index", "tag": "Index", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false, "value_set": "IRIndex", "data_type": "String", "risk_factor_type": "ir_index"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Spreads", "tag": "Spreads", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Spreads/Spread", "tag": "Spread", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/FixingDays", "tag": "FixingDays", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Integer"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/IsInArrears", "tag": "IsInArrears", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/LastRecentPeriod", "tag": "LastRecentPeriod", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/LastRecentPeriodCalendar", "tag": "LastRecentPeriodCalendar", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Lookback", "tag": "Lookback", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/RateCutoff", "tag": "RateCutoff", "is_field": true, "value": "0", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Integer", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/IsAveraged", "tag": "IsAveraged", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/HasSubPeriods", "tag": "HasSubPeriods", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/IncludeSpread", "tag": "IncludeSpread", "is_field": true, "value": "false", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/IsNotResettingXCCY", "tag": "IsNotResettingXCCY", "is_field": true, "value": "false", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Caps", "tag": "Caps", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Caps/Cap", "tag": "Cap", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Floors", "tag": "Floors", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Floors/Floor", "tag": "Floor", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Gearings", "tag": "Gearings", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/Gearings/Gearing", "tag": "Gearing", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/NakedOption", "tag": "NakedOption", "is_field": true, "value": null, "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "value_set": "Boolean", "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/LocalCapFloor", "tag": "LocalCapFloor", "is_field": true, "value": "false", "level": 4, "type": "field", "is_choice_based": false, "is_optional": true, "data_type": "Boolean", "is_activatable": true}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/FixingSchedule", "tag": "FixingSchedule", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/ResetSchedule", "tag": "ResetSchedule", "is_field": false, "value": null, "level": 4, "type": "container", "is_choice_based": false}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/HistoricalFixings", "tag": "HistoricalFixings", "is_field": false, "value": null, "level": 4, "type": "array"}
{"xpath": "Trade/SwaptionData/LegData[2]/FloatingLegData/HistoricalFixings/Fixing", "tag": "Fixing", "is_field": true, "value": null, "level": 5, "type": "field", "is_choice_based": false, "is_optional": false, "data_type": "Double"}
```
