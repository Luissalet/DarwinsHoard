# Skills improved by implemented repositories

Research → Skills que mejoran los repos implantados lists every repository delivery
declared integrated, with its target app, commit and linked skill. Pagination includes
unmatched deliveries. The search filters the current page. A discovery's genealogy
and the radar plan/run expose the same map as `skill_impacts` and
`implemented_skill_impacts` respectively.

The app reads the published skill library and the Hub's current shelf overview;
when the Hub is unavailable it can suggest procedures explicitly written for the
target app. Candidates need at least two shared non-generic terms. They remain
labelled suggestions: neither a term match nor a declared integrated delivery
proves that a skill was improved. Existing commit ancestry and verification remain
separate and unchanged.

Document a link with the delivery, skill slug and the specific contribution. Read
the complete procedure before choosing. Links live in delivery evidence and keep
the skill version and SHA256 at the time; later reads flag changes or missing
skills. Removing a link preserves the delivery and its commit evidence. It does
not edit or assign the skill and never starts another app or a model.

HTTP: `GET /api/skill-impacts?source_id=&target=&limit=100&offset=0`,
`POST /api/skill-impacts/link {delivery_id, slug, reason, on?}`,
`GET /api/skill-impacts/skill?slug=...`.

MCP: `darwin_skill_impacts`, `darwin_skill_impact_link`,
`darwin_skill_impact_read`. The regular `darwin_source`, `darwin_radar_plan`
and `darwin_radar_run` include the map too. No migration of existing records is
required; an old delivery without a link is reported as suggested or unmatched.
