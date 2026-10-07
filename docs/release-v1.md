# Skills Morning Brief 1.0.0

## Product

Public GitHub Skills monitoring, useful historical Skills, repository popularity, measured growth and official AI/Agent news. Public reading is available immediately; personal recommendations, capability scanning, imported inventories and workspace feedback are optional.

Python 3.11+ local service with a browser reader, bundled public summaries and 20px default text. Windows daily scheduling supports catch-up after a missed run. Keys come from the user's environment, temporary input or the current GitHub CLI login, and remain outside distribution assets.

## Release verification

- 65 Python tests passed locally on Windows / Python 3.14.7. Coverage includes private session enforcement, CSRF and origin checks, workspace isolation, public field allowlists, refusal to forward credentials by redirects, source fingerprints, real growth windows, occupied ports, process locks and failed-run persistence.
- JavaScript syntax checks passed. Nine DOM/HTTP flows passed: public home and navigation, optional entry, empty-field cancellation, Escape, automatic directory discovery, explicit scanning, back navigation and returning home. These checks use an isolated fixture with synthetic capabilities, not another real user's installation.
- Current user's existing profile was preserved. Direct HTTP checks confirm that the public page is available and anonymous private API requests are rejected.
- The old Windows task failed with exit code 1 because its PowerShell script was blocked by execution policy. The replacement uses a process-scoped execution parameter and the new product name. An initial anonymous GitHub refresh was degraded by rate limits; authenticated collection reuses the existing GitHub CLI login in memory.
- Public monitoring uses a bounded request budget and repository rotation. Some source files remain pending; one large official Skill exceeded the 100KB research limit. Partial coverage is shown as partial rather than complete.
- The final manual Task Scheduler run started at 2026-10-08 02:07:42 and completed its refresh at 02:08:44 Asia/Shanghai. Task exit code was 0; the monitor recorded no failed source or editor, 37 GitHub requests, 92 reviewed public Skills across 14 retained repositories, and 7 news items. Repository coverage remains incremental. The next scheduled run is 2026-10-08 08:30 Asia/Shanghai.
- Stage, commit history and distribution scans are required before publication. The ZIP and SHA-256 checksum are attached to the Release; publication metadata records the actual commit SHA separately.

## Verification limits

The managed browser connection could not start in this environment, so visual screenshot verification remains unverified. DOM interaction checks do not establish actual pixel layout. Cross-platform and Python 3.11 CI is configured and must be checked in the repository after push. Real personal model calls for every supported Agent and third-party Skill execution are not part of this release validation.

The daily task runs when this Windows user is logged in and the computer is on. A manual task trigger verifies the full execution path; the next natural clock-triggered run must be checked afterward. This release provides a local application and public source repository, not an always-online hosted deployment or outbound notification service.

## Recovery

If a refresh fails, previously completed catalog items remain readable. Review `.runtime/latest-monitor.json`, retry `python -m morningpaper monitor`, and open the reader again if needed. To pause daily operation, disable `Skills Morning Brief - Daily` in Windows Task Scheduler.

Private data is retained separately from application code. Before changing application versions, preserve the OS user's `AgentSkillShelf` directory. Replace application files with a reviewed archive or commit; do not copy public ZIP files over private records. To undo a published code change, create a normal Git revert commit. A withdrawn release should be marked draft or removed with its assets while keeping local audit evidence; never force-rewrite shared history.
