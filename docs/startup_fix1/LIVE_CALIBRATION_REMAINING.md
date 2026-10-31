# Remaining implementation before a real calibrated model

1. Implement a cordon-specific trial adapter on the existing 15A2 controller:
   current accepted state -> permitted 2025 TG/TD change -> native realization
   -> assignment -> ACTUAL saved-path cordon evaluation -> accept/rollback.
   Do not use PROFILE488 12D score as the acceptance objective.
2. Bind actual 2025 formula/parameter/matrix authorities; frozen matrices
   must remain fixed. Shadow guidance is not a realizable model update.
3. Close pair semantics, year bridge, direction scope and C17 policy using
   explicit evidence; not automatic blanket approvals in a launcher.
4. Native Windows/Visum one-candidate acceptance and rollback fault test,
   including full new-path coverage after new positive OD emerges.
5. Only then enable a separate, explicit APPLY interface. This release has none.

The two new scripts solve startup/data acquisition/diagnostics, not the
missing transactions above. They do not run a 100-cycle calibration.
