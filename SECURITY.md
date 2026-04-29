# Security Policy

## Supported scope

VibeSensor is an active-development lab project. Security fixes are handled on
`main` first and are included in the latest GitHub release when a release is
needed for Raspberry Pi or firmware users.

| Target | Security support |
| ------ | ---------------- |
| `main` | Supported |
| Latest GitHub release | Supported when a fix needs a release artifact |
| Older releases, branches, forks, or local deployments | Not supported |

## Reporting a vulnerability

Use GitHub private vulnerability reporting from this repository's Security tab
when it is available. Include the affected component, reproduction steps, impact,
and any logs or screenshots that do not expose real credentials.

If private vulnerability reporting is unavailable, open a GitHub issue titled
`Security disclosure request` with no exploit details, secrets, logs, or affected
host information. A maintainer will move the discussion to a private channel.

Do not publish proof-of-concept exploit details until a maintainer has confirmed
the report and a fix or mitigation is available.

## Expected response

Security reports are triaged against the active `main` branch. Accepted reports
are fixed on `main` and released when users need a new artifact. Reports for
unsupported old releases or local forks may be declined unless they also affect
the supported scope above.
