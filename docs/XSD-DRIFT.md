# XSD <-> Code Drift

The xsd/*.xsd schemas validate XML structure only and are known incomplete. `fromXML()` in the C++ is authoritative for what ORE actually accepts - see the sections below for where the two diverge, and README.md's Limitations section.

<!-- BEGIN XSD-DRIFT AUTO-GENERATED (oregraph merge) -->

## (c) Match counts by tier

- Tier 1 (EXTRACTED, `<T>Data` from the trade-type registry): 109
- Tier 2 (EXTRACTED, exact class-label match): 35
- Tier 3 (INFERRED, normalised match): 124
- Total matched xsd type names: 268 / 955
- `schema_for` edges written: 268

Trade-type registry: 113 confirmed TradeType registrations (`ORE_REGISTER_TRADE_BUILDER` in databuilders.cpp), cross-referenced against 137 classes found in portfolio/*.{hpp,cpp} transitively inheriting from Trade.
24 of those classes are not independently registered TradeTypes (abstract intermediates used only to share code, e.g. scaffolding base classes, or scripted-trade example payloads dispatched generically under `ScriptedTrade`): `Accumulator`, `AsianOption`, `Autocallable_01`, `BarrierOption`, `BasketOption`, `BasketVarianceSwap`, `BestEntryOption`, `CliquetOption`, `EquityDerivative`, `EquityOptionWithBarrier`, `EquitySingleAssetDerivative`, `FxDerivative`, `FxOptionWithBarrier`, `FxSingleAssetDerivative`, `GenericBarrierOption`, `PairwiseVarSwap`, `PerformanceOption_01`, `RainbowOption`, `StrikeResettableOption`, `TaRF`, `VanillaOptionTrade`, `VarSwap`, `WindowBarrierOption`, `WorstOfBasketSwap`

Cross-check: the merged graph's own `inherits` edges into any node labelled `Trade` show 32 direct subclasses (`Ascot`, `Bond`, `BondFuture`, `BondPosition`, `BondRepo`, `BondTRS`, `CBO`, `CallableBond`, `CapFloor`, `CashPosition`, `CommodityForward`, `CommodityPosition`, `ConvertibleBond`, `CreditDefaultSwap`, `CreditDefaultSwapOption`, `CreditLinkedSwap`, `EquityAutoDeltaHedgedOption`, `EquityForward`, `EquityOptionPosition`, `EquityPosition`, +12 more), against 56 found by scanning portfolio/*.{hpp,cpp} directly for `class X : public Trade`. graphify emits one unresolved-reference placeholder node per file that mentions the external `Trade` base rather than one canonical node, and even a perfect match only sees *direct* inheritance - not the multi-level chains (e.g. `CrossCurrencySwap -> Swap -> Trade`) the registry above also covers - so a large gap here is expected, not a bug.

## (a) XSD types with no matching code

687 of 955 named xsd types/elements across all xsd/*.xsd files matched no code at any tier - schema for something renamed, removed, or never implemented (or, for many non-instruments.xsd files, a config/enum type with no dedicated parsing class of its own, e.g. a nested value type). Not all of these are bugs; each is worth a human look.

- `xsd/calendaradjustment.xsd`: `CalendarAdjustments`, `Dates`, `calendaradjustment`, `newcalendar`
- `xsd/conventions.xsd`: `AverageOIS`, `BMABasisSwap`, `BondYield`, `CDS`, `CmsSpreadOption`, `CommodityFuture`, `CrossCurrencyBasis`, `CrossCurrencyFixFloat`, `Deposit`, `FRA`, `Future`, `FxOptionTimeWeighting`, `IborIndex`, `OIS`, `OvernightIndex`, `SwapIndex`, `TenorBasisSwap`, `TenorBasisTwoSwap`, `Zero`, `ZeroInflationIndex`, `averageOISType`, `averagingDataType`, `bmaBasisSwapType`, `bondYield`, `cdsConventionsType`, `cmsSpreadOptionType`, `commodityForwardType`, `commodityFutureType`, `continuationMappingType`, `continuationMappingsType`, `crossCurrencyBasisType`, `crossCurrencyFixFloatType`, `depositType`, `fraType`, `futureType`, `fxOptionTimeWeighting`, `fxType`, `iborIndexType`, `inflationswapType`, `nthWeekdayType`, `offPeakPowerIndexDataType`, `oisType`, `overnightIndexType`, `prohibitedExpiriesBdcType`, `prohibitedExpiriesType`, `swapIndexType`, `swapType`, `tenorBasisSwapType`, `tenorBasisTwoSwapType`, `zeroInflationIndexType`, `zeroType`
- `xsd/counterparty.xsd`: `CounterpartyInformation`, `counterPartyCorrelations`, `counterparties`, `counterparty`, `counterpartyInformation`, `creditQualityType`
- `xsd/creditsimulation.xsd`: `CreditSimulation`, `creditsimulation`, `entities`, `entity`, `risk`, `transitionmatrices`, `transitionmatrix`
- `xsd/currencyconfig.xsd`: `currencyDefinition`
- `xsd/curveconfig.xsd`: `BondYieldShifted`, `BondYieldShiftedType`, `CrossCurrency`, `CurveConfiguration`, `Direct`, `DiscountRatio`, `FittedBond`, `IborFallback`, `Simple`, `TenorBasis`, `WeightedAverage`, `YieldPlusDefault`, `ZeroSpread`, `aoisSegmentType`, `baseCorrelation`, `baseCorrelations`, `bootstrapConfigType`, `capFloorVolatilities`, `capFloorVolatility`, `cdsVolatilities`, `cdsVolatility`, `commVolQuoteSuffix`, `commodityBasisConfig`, `commodityInterpolationType`, `commodityVolatilities`, `compositeQuoteType`, `correlation`, `correlations`, `crossCurrencySegmentType`, `crossCurrencySegmentTypeType`, `curveconfiguration`, `defaultCurve`, `defaultCurveType`, `defaultCurves`, `directSegmentType`, `directSegmentTypeType`, `discountRatioCurveElement`, `discountRatioType`, `discountRatioTypeType`, `dividendInterpolation`, `equityCurve`, `equityCurves`, `equityVolatilities`, `equityVolatility`, `factorType`, `fittedBondType`, `fxSpot`, `fxSpots`, `fxVolatilities`, `fxVolatility`, `globalReportConfiguration`, `iborFallbackType`, `indexFactorsType`, `inflSegmentsType`, `inflationCapFloorVolatility`, `inflationCapFloorVolatlities`, `inflationCurve`, `inflationCurves`, `inlfSegmentType`, `minMaxType`, `offPeakDailyType`, `oneDimSolverConfigType`, `parametricSmileConfig`, `parametricSmileConfigCalibration`, `parametricSmileConfigParameter`, `parametricSmileConfigParameters`, `priceInfoType`, `priceSegmentType`, `priceSegmentsType`, `proxySurface`, `quoteType`, `reportConfiguration`, `seasonalityType`, `securities`, `security`, `segmentsType`, `simCommodityCurve`, `simCommodityCurves`, `simpleSegmentType`, `simpleSegmentTypeType`, `swaptionVolatilities`, `swaptionVolatility`, `tenorBasisSegmentType`, `tenorBasisSegmentTypeType`, `weightedAverageType`, `yieldCurve`, `yieldCurveReport`, `yieldCurves`, `yieldPlusDefaultType`, `yieldVolatilities`, `yieldVolatility`, `zeroSpreadSegmentTypeType`, `zeroSpreadType`
- `xsd/historicalreturnconfig.xsd`: `ReturnConfiguration`, `ReturnEnum`, `ReturnType`
- `xsd/iborfallbackconfig.xsd`: `iborFallbackFallback`, `iborFallbackFallbacks`, `iborFallbackGlobalSettings`
- `xsd/input.xsd`: `Portfolio`, `SubTrade`, `Trade`, `componentSubTrade`, `componentTrade`, `portfolio`, `subTradeGroup`, `trade`
- `xsd/instruments.xsd`: `Accumulator01Data`, `Accumulator02Data`, `ArcOptionData`, `AsianBasketOptionData`, `AsianIrCapFloorData`, `AsianRainbowCallSpreadOptionData`, `AssetLinkedCliquetOptionData`, `AverageStrikeBasketOptionData`, `BestOfAirbagData`, `BestOfAssetOrCashRainbowOptionData`, `CMSCapFloorBarrierData`, `CallableRangeAccrualData`, `CdoData`, `CommodityRevenueOptionData`, `CommodityWindowBarierOptionData`, `ConditionalVarianceSwap01Data`, `ConditionalVarianceSwap02Data`, `ConstantMaturityVolatilitySwapData`, `CorrelationSwapData`, `CorridorVarianceDispersionSwapData`, `CorridorVarianceSwapData`, `CreditCurveId`, `DualEuroBinaryOptionData`, `DualEuroBinaryOptionDoubleKOData`, `EuropeanRainbowCallSpreadOptionData`, `ExerciseDates`, `ExerciseSchedule`, `ExtendedAccumulatorData`, `FixedStrikeForwardStartingOptionData`, `FloatingStrikeForwardStartingOptionData`, `FlooredAverageCPIZCIISData`, `ForwardStartingSwaptionData`, `ForwardVolatilityAgreementData`, `FundingResetGracePeriod`, `GammaSwapData`, `IndexedCorridorVarianceSwapData`, `IrregularYYIISData`, `KIKOCorridorVarianceSwapData`, `KIKOVarianceSwapData`, `KOCorridorVarianceDispersionSwapData`, `LPISwapData`, `LadderLockInOptionData`, `LapseHedgeSwapData`, `LegData`, `Level`, `LevelData`, `LookbackCallBasketOptionData`, `LookbackPutBasketOptionData`, `MaxRainbowOptionData`, `MinRainbowOptionData`, `MovingMaxYYIISData`, `Name`, `NettingSetId`, `NotionalType`, `PairwiseGeometricVarianceDispersionSwapData`, `PairwiseVarianceSwapData`, `RainbowCallSpreadBarrierOptionData`, `ReferenceInformation`, `Rules`, `Underlyings`, `VanillaBasketOptionData`, `VarianceDispersionSwapData`, `VarianceOptionData`, `VarianceSwapData`, `VolatilityBarrierOptionData`, `WorstOfAssetOrCashRainbowOptionData`, `WorstPerformanceRainbowOption01Data`, `WorstPerformanceRainbowOption02Data`, `WorstPerformanceRainbowOption03Data`, `WorstPerformanceRainbowOption04Data`, `WorstPerformanceRainbowOption05Data`, `WorstPerformanceRainbowOption06Data`, `WorstPerformanceRainbowOption07Data`, `WorstPerformanceRainbowOption08Data`, `WorstPerformanceRainbowOption09Data`, `YYLegData`, `accumulator01Data`, `accumulator02Data`, `arcOptionData`, `asianBasketOptionData`, `asianIrCapFloorData`, `asianRainbowCallSpreadOptionData`, `assetBackedCreditDefaultSwapData`, `assetLinkedCliquetOptionData`, `auctionSettlementInformation`, `averageStrikeBasketOptionData`, `barrierCompare`, `barrierStyle`, `barrierType`, `basketVarianceSwapData2`, `bestEntryOptionData2`, `bestOfAirbagData`, `bestOfAssetOrCashRainbowOptionData`, `bgSwapData`, `bondData`, `callableBondCallData`, `callableBondData`, `callableRangeAccrualData`, `callsPutsType`, `caps`, `cbCallData`, `cbContingentConversionData`, `cbConversionData`, `cbConversionResetData`, `cbDividendProtectionData`, `cbExchangeableData`, `cbMandatoryConversionData`, `cbPepsData`, `cboBondBasketData`, `cboInvestment`, `cboStructure`, `cbotranche`, `cbotranches`, `cdoData`, `cdsOptionstrikeType`, `cmsCapFloorBarrierData`, `commForwardSettlementData`, `commodityPayRelativeToType`, `commodityPositionData`, `commodityQuantityFrequencyType`, `commodityRevenueOptionData`, `commoditySpreadOptionData`, `commoditySpreadOptionStripPaymentData`, `compositeTradeComponents`, `conditionalVarianceSwap01Data`, `conditionalVarianceSwap02Data`, `constantMaturityVolatilitySwapData`, `convertibleBondData`, `correlationSwapData`, `corridorVarianceDispersionSwapData`, `corridorVarianceSwapData`, `creditCurveIdType`, `creditDefaultSwapData`, `deliveryBasket`, `dualEuroBinaryOptionData`, `dualEuroBinaryOptionDoubleKOData`, `emptyFloat`, `eqBarrierOptionData`, `eqDigitalOptionData`, `eqForwardSettlementData`, `eqOutperformanceOptionData`, `eqTouchOptionData`, `equityAutoDeltaHedgedUnderlyingData`, `equityOptionPositionData`, `equityPositionData`, `europeanRainbowCallSpreadOptionData`, `exchanges`, `exerciseDatesGroup`, `extendedAccumulatorData`, `fixedStrikeForwardStartingOptionData`, `floatWithAttribute`, `floatingStrikeForwardStartingOptionData`, `flooredAverageCPIZCIISData`, `floors`, `forwardStartingSwaptionData`, `forwardVolatilityAgreementData`, `fundingData`, `fxForwardSettlementData`, `fxTermsData`, `fxreset`, `gammaSwapData`, `gearings`, `genericBarrierOptionData`, `genericBarrierOptionDataRaw`, `indexCreditDefaultSwapData`, `indexedCorridorVarianceSwapData`, `irregularYYIISData`, `kikoCorridorVarianceSwapData`, `kikoVarianceSwapData`, `koCorridorVarianceDispersionSwapData`, `ladderLockInOptionData`, `lapseHedgeSwapData`, `legData`, `legDataType`, `legData_capfloor`, `legType`, `levelData`, `levelGroup`, `longShortsType`, `lookbackCallBasketOptionData`, `lookbackPutBasketOptionData`, `maxRainbowOptionData`, `minRainbowOptionData`, `movingMaxYYIISData`, `nameData`, `nettingSetGroup`, `notionalCalculation`, `optionData`, `oreTradeType`, `pairwiseGeometricVarianceDispersionSwapData`, `pairwiseVarianceSwapData1`, `pairwiseVarianceSwapData2`, `priceType`, `pricesType`, `pricingDateRuleType`, `quantitiesType`, `rainbowCallSpreadBarrierOptionData`, `rpaData`, `settlementData`, `singleUnderlyingAsianOptionData`, `spreads`, `stFreeStyleBarrierType`, `stFreeStyleBarrierTypeVector`, `stFreeStyleBarrierTypeVectorBase`, `stFreeStyleBool`, `stFreeStyleBoolVector`, `stFreeStyleBoolVectorBase`, `stFreeStyleCurrency`, `stFreeStyleCurrencyVector`, `stFreeStyleCurrencyVectorBase`, `stFreeStyleDayCounter`, `stFreeStyleDayCounterVector`, `stFreeStyleDayCounterVectorBase`, `stFreeStyleEvent`, `stFreeStyleEventSchedule`, `stFreeStyleEventScheduleBase`, `stFreeStyleIndex`, `stFreeStyleIndexVector`, `stFreeStyleIndexVectorBase`, `stFreeStyleLongShort`, `stFreeStyleLongShortVector`, `stFreeStyleLongShortVectorBase`, `stFreeStyleNumber`, `stFreeStyleNumberVector`, `stFreeStyleNumberVectorBase`, `stFreeStyleOptionType`, `stFreeStyleOptionTypeVector`, `stFreeStyleOptionTypeVectorBase`, `strikeGroup`, `strikePriceData`, `strikeResettableOptionData2`, `strikeYieldData`, `strikes`, `stubInterpolation`, `tarfData2`, `tlockData`, `totalReturnData`, `totalReturnSwapData`, `tradeActionOwner`, `tradeActionType`, `tradeLevelFixings`, `tranches`, `trsAdditionalCashflowData`, `trsFundingData`, `trsFxConversion`, `trsNotionalType`, `trsReturnData`, `trsUnderlyingData`, `underlyingTypes`, `underlyings`, `vanillaBasketOptionData`, `varianceDispersionSwapData`, `varianceOptionData`, `varianceSwapData`, `volBarrierOptionData`, `windowBarrierOptionData2`, `worstOfAssetOrCashRainbowOptionData`, `worstOfBasketSwapData2`, `worstPerformanceRainbowOption01Data`, `worstPerformanceRainbowOption02Data`, `worstPerformanceRainbowOption03Data`, `worstPerformanceRainbowOption04Data`, `worstPerformanceRainbowOption05Data`, `worstPerformanceRainbowOption06Data`, `worstPerformanceRainbowOption07Data`, `worstPerformanceRainbowOption08Data`, `worstPerformanceRainbowOption09Data`
- `xsd/nettingsetdefinitions.xsd`: `csaType`, `independentAmountType`
- `xsd/ore.xsd`: `ORE`, `analyticsType`, `ore`, `parameterListType`
- `xsd/ore_types.xsd`: `CurrencyHedgedIndexRebalancingStrategy`, `CurrencyHedgedIndexRehedgingStrategy`, `Derived`, `DerivedSchedule`, `DerivedScheduleGroup`, `DerivedScheduleType`, `amortizationType`, `averagingDataPeriodType`, `bondPriceType`, `bool`, `businessDayConvention`, `calendar`, `cdsDocClauseType`, `cdsTierType`, `cdsType`, `compounding`, `correlationQuoteType`, `correlationType`, `currencyCode`, `currencyPair`, `date`, `dateRule`, `dayOfMonth`, `dimensionType`, `equityType`, `exerciseStyle`, `extendedCurrencyCode`, `extrapolationType`, `frequencyType`, `futureDateGenerationRule`, `fxVolInterpolation`, `indexNameType`, `inflationType`, `interpolationMethodType`, `interpolationVariableType`, `isodate`, `longShort`, `momentType`, `monthType`, `mporCashFlowMode`, `non-negative-decimal`, `optionPayRelativeTo`, `optionType`, `overnightIndexFutureNettingType`, `parametricVolatilityParameterCalibration`, `paymentLag`, `period`, `positiveDecimal`, `premiumCurrencyCode`, `priceSegmentTypeType`, `publicationRoll`, `recoveryRate`, `riskFactorKeyType`, `roundingType`, `settlementMethod`, `settlementType`, `shiftScheme`, `shiftType`, `smileType`, `strikeAtmType`, `strikeDeltaType`, `strikeMoneynessType`, `subPeriodsCouponType`, `sviModelVariantType`, `volatilityInterpolationType`, `volatilityType`, `weekdayType`, `weightType`
- `xsd/pricingengines.xsd`: `PricingEngines`, `globalParameters`, `parameter`, `pricingengines`, `product`
- `xsd/referencedata.xsd`: `BondFutureReferenceData`, `BondReferenceData`, `CallableBondReferenceData`, `CboReferenceData`, `CommodityIndexReferenceData`, `ConvertibleBondReferenceData`, `CreditIndexReferenceData`, `CreditReferenceData`, `CurrencyHedgedEquityIndexReferenceData`, `EquityIndexReferenceData`, `EquityReferenceData`, `PortfolioBasketReferenceData`, `ReferenceData`, `currencyHedgedIndexReferenceDatum`
- `xsd/scriptlibrary.xsd`: `ScriptLibrary`, `ore_script`
- `xsd/sensitivity.xsd`: `basecorrelation`, `basecorrelations`, `capfloorvolatilities`, `capfloorvolatility`, `cdsvolatilities`, `cdsvolatility`, `commodityCurve`, `commodityCurves`, `commodityvolatilities`, `correlationcurve`, `correlationcurves`, `cpicapfloorvolatilities`, `cpicapfloorvolatility`, `creditcurve`, `creditcurves`, `crossgammafilter`, `discountcurve`, `discountcurves`, `dividendyield`, `dividendyields`, `equityspot`, `equityspots`, `equityvolatilities`, `equityvolatility`, `fxspot`, `fxspots`, `fxvolatilities`, `fxvolatility`, `indexcurve`, `indexcurves`, `parConversionMatrixRegularisation`, `parExcludes`, `parconversion`, `recoveryrate`, `recoveryrates`, `securityspread`, `securityspreads`, `setRiskFactorKeyTypes`, `shiftSchemeEntry`, `shiftSizeEntry`, `shiftTypeEntry`, `survivalprobabilities`, `survivalprobability`, `swaptionvolatilities`, `swaptionvolatility`, `yieldcurve`, `yieldcurves`, `yieldvolatilities`, `yieldvolatility`, `yycapfloorvolatilities`, `yycapfloorvolatility`, `yyinflationindexcurve`, `yyinflationindexcurves`, `zeroinflationindexcurve`, `zeroinflationindexcurves`
- `xsd/simmcalibration.xsd`: `SIMMCalibrationData`, `commodity`, `concentrationThresholds`, `creditNonQualifying`, `creditQualifying`, `currencyLists`, `equity`, `interestRate`, `irfxConcentrationThresholds`, `simmCalibration`
- `xsd/simulation.xsd`: `CrossAssetModel`, `Simulation`, `SobolBrownianGeneratorOrdering`, `SobolRsgDirectionIntegers`, `boundaryConstraint`, `calibrationCpiCapFloor`, `calibrationTypeType`, `calibrationYoYCapFloor`, `calibrationYoYSwap`, `cir`, `correlationValue`, `crossAssetLGM`, `crossAssetModel`, `crossCurrencyLGM`, `currencyCodeWithDefault`, `curveAlgebra`, `curveAlgebraCurve`, `curveAlgebraCurveOperation`, `default`, `defaultCurveExtrapolation`, `discretizationType`, `dodgsonKainth`, `floatSpreadMappingType`, `hw`, `jarrowYildrim`, `localVolSimpleMcParameters`, `market`, `measureType`, `mporMode`, `paramTypeType`, `reversionParameter`, `reversionTypeType`, `salvagingAlgoType`, `sequenceType`, `simulation`, `timeDecayType`, `volatilityParameter`, `volatilityTypeType`, `ycExtrapolation`, `ycInterpolation`
- `xsd/stress.xsd`: `StressTesting`, `stresscapfloorvolatilities`, `stresscapfloorvolatility`, `stresscommoditycurve`, `stresscommoditycurves`, `stresscommodityvolatilities`, `stresscommodityvolatility`, `stressdiscountcurve`, `stressdiscountcurves`, `stressfxvolatilities`, `stressfxvolatility`, `stressindexcurve`, `stressindexcurves`, `stresssurvivalprobabilities`, `stresssurvivalprobability`, `stresstest`, `stresstesting`, `stresstestparshifts`, `stressyieldcurve`, `stressyieldcurves`
- `xsd/todaysmarket.xsd`: `baseCorrelationsType`, `capFloorVolatilitiesType`, `cdsVolatilitiesType`, `commodityCurvesType`, `commodityVolatilitiesType`, `configurationType`, `correlationsType`, `defaultCurvesType`, `discountCurvesType`, `equityCurvesType`, `equityVolatilitiesType`, `fxSpotsType`, `fxVolatilitiesType`, `indexForwardingCurvesType`, `securitiesType`, `swapIndexCurvesType`, `swaptionVolatilitiesType`, `todaysmarket`, `yieldCurvesType`, `yieldVolatilitiesType`, `yyInflationCapFloorVolatilitiesType`, `yyInflationIndexCurvesType`, `zeroInflationCapFloorVolatilitiesType`, `zeroInflationIndexCurvesType`

## (b) Code trade types with no XSD type

4 of 113 registered TradeTypes have no matching xsd type at any tier - **this is the validation coverage gap**: ORE will build every one of these from XML with no schema check on its fields at all.

- `BondPosition` - `BondPosition` (bondposition.hpp)
- `CommodityWindowBarrierOption` - `CommodityWindowBarrierOption` (windowbarrieroption.hpp)
- `Failed` - `FailedTrade` (failedtrade.hpp)
- `SyntheticCDO` - `SyntheticCDO` (cdo.hpp)

<!-- END XSD-DRIFT AUTO-GENERATED -->

## Field-level drift (A6 sample)

The counts above are name-level: a trade type "has an xsd type" if some
complexType/element name matches. That says nothing about whether the fields
*inside* match. This section reads `fromXML()` for five trade types spanning
simple to complex and compares them field-by-field against instruments.xsd's
declaration for the same trade, by hand - not generated, not re-run by
`oregraph merge`. This is a findings note; nothing here has been fixed.

Divergence showed up on **3 of 5** samples, including one genuine structural
bug (not just a missing/extra field) and one case (ScriptedTrade) that no
XSD can represent by design. That is enough on its own to justify a
generate-schema-from-code project as separate follow-up work: the schema is
not just incomplete at the edges, it actively disagrees with the code on
what a valid trade of these types looks like.

### FxForward - clean match

`FxForward::fromXML()` (`OREData/ored/portfolio/fxforward.cpp:216`) reads
`ValueDate`, `BoughtCurrency`, `BoughtAmount`, `SoldCurrency`, `SoldAmount`
(all required) and optional `Settlement` / `SettlementData` (itself optional
`Currency`/`FXIndex`/`Date`/`Rules{PaymentLag,PaymentCalendar,
PaymentConvention}`). `fxForwardData` and `fxForwardSettlementData` in
instruments.xsd declare exactly this field set with exactly this
required/optional split. No drift.

### Swap - the shared type carries fields Swap itself never reads

`Swap::fromXML()` (`OREData/ored/portfolio/swap.cpp:385`) reads only
`Settlement` (optional) and a repeated, required `LegData` array. But
`swapData` in instruments.xsd - the type `SwapData`/`CrossCurrencySwapData`/
`InflationSwapData`/`EquitySwapData` all bind to - also declares
`RoundNettedFloatingLegs` (`xs:boolean`, optional) and `NettingPrecision`
(`xs:nonNegativeInteger`, optional). Neither is read anywhere in
`Swap::fromXML()`.

Those two fields *are* read - by `CommoditySwap::fromXML()`
(`commodityswap.cpp:450-452`), a different class entirely, whose own xsd
type is `commoditySwapData`, not `swapData`. It looks like
`RoundNettedFloatingLegs`/`NettingPrecision` were added to the shared
`swapData` type (perhaps by copy from `commoditySwapData`, or in
anticipation of adding netting support to plain `Swap`) without adding the
matching read in `Swap::fromXML()`. A user setting
`<RoundNettedFloatingLegs>true</RoundNettedFloatingLegs>` inside a
`<SwapData>` block gets no error and no effect - the schema says it's valid,
the code silently ignores it.

### Swaption - clean match, one harmless overspecification

`Swaption::fromXML()` (`swaption.cpp:788`) reads required `OptionData` and a
required, repeated `LegData`, both looked up by tag name regardless of
position. `swaptionData` declares the same two fields with the same
cardinality - but as an `xs:choice` of two `xs:sequence`s (OptionData-then-
LegData, or LegData-then-OptionData), i.e. it encodes an ordering
constraint. The code has no such constraint - `XMLUtils::getChildNode`/
`getChildrenNodes` find children by name, not position - so the xsd is
stricter than the code on order, and looser than reality is: a
`<SwaptionData>` with `LegData` and `OptionData` interleaved oddly would
still be accepted by `Swaption::fromXML()` but might not validate against
either declared sequence. Cosmetic, not a real gap.

### CommoditySwap - the schema names the wrong element entirely

instruments.xsd's `oreTradeData` dispatch declares
`<xs:element type="commoditySwapData" name="CommoditySwapData"/>` - so a
schema-valid `CommoditySwap` trade should wrap its fields in
`<CommoditySwapData>`. But `CommoditySwap::fromXML()`
(`commodityswap.cpp:434-456`) does
`XMLUtils::getChildNode(node, "SwapData")` - a **literal, hardcoded
`"SwapData"`**, not `tradeType() + "Data"` the way the plain `Swap` class
builds its lookup. Checked against a real, working example
(`Examples/Exposure/Input/portfolio_commodity.xml:46,52`): `TradeType` is
`CommoditySwap` and the data wrapper is indeed `<SwapData>`, confirming the
code (and every real example file) is internally consistent - it's the xsd
that's wrong, declaring a wrapper element name (`CommoditySwapData`) that
does not match what the parser actually looks for or what real portfolios
use. Any tool that generates XML strictly from the schema (`CommoditySwapData`)
would produce a file ORE silently fails to populate (`QL_REQUIRE(swapNode,
"No SwapData Node")` would fire, so at least it isn't silent - but the
schema itself is actively misleading about the correct element name).

### ScriptedTrade - a shape no XSD can represent

`ScriptedTrade::fromXML()` (`scriptedtrade.cpp:269`) has two branches. The
"native" branch (a `<ScriptedTradeData>` node with `ScriptName`/`Script`,
`Data/{Number,Index,Currency,Daycounter,Event}*`) matches
`scriptedTradeData` in instruments.xsd reasonably closely. But when no
`<ScriptedTradeData>` node is found, `fromXML()` falls back to "freestyle"
parsing (`scriptedtrade.cpp:317` on): it scans the trade's children for
*any* node whose tag ends in `Data`, treats the `xxx` prefix as the script
name, and parses `xxx`'s fields dynamically against that script's declared
inputs - e.g. a trade could use `<Autocallable_01Data>` as its wrapper with
`TradeType=ScriptedTrade`, and the "Autocallable_01" script name is inferred
from the tag itself, never declared anywhere. instruments.xsd's
`oreTradeData` group has exactly one binding for ScriptedTrade
(`ScriptedTradeData`) and cannot express "any tag ending in Data, meaning is
resolved at runtime against a script library" - that's not a documentation
gap, it's a shape XSD's closed, enumerated-choice model cannot represent at
all without listing every script name that will ever exist as its own
element. This is the strongest case in the sample for schema generation
being the wrong fix and runtime/script-level validation being the right one
for this trade type specifically.
