# Candidate Application History Sync

The former rejection-sheet sync is retired. The configured sheet and existing
local history are migration evidence only; use the explicit JH-308 cutover
command documented in `docs/OPERATIONS.md`. The bounded
`historical_application_evidence` table is the runtime source for unlinked
employer/role context, while exact job outcomes live in JH-305.
