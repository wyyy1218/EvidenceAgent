# Evaluation limitations (S47)

- Single-author human blind review (S46); no inter-annotator agreement.
- Release system remains **E0**; E1/E2 are research_only under S40.
- B1 mass `failed`/`failed_policy` must stay in the denominator.
- DRBench/live are external small subsets; not official full leaderboards; not mixed into main aggregates.
- Live environment drift is expected; AB/BA reduces but does not eliminate order effects.
- Preference data below original 600/100 target; do not claim target-scale DPO completion.
- Pretraining contamination cannot be fully excluded.
- Token proxy prices are not invoices.
- Public hosting may be incomplete; personal access ≠ public deployment.
