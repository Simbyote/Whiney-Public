# Security policy

Whiney downloads archives and unpacks them on players' PCs, runs programs,
and can ask Windows for administrator rights (to add a firewall rule). A
flaw in any of that can reach every player of a pack, so please report it
privately.

## Reporting

Use the repository's **Security** tab, then **Report a vulnerability**. Do
not open a public issue. Include:

- what an attacker could do, and what they would need (a crafted archive,
  a tampered download, a malicious crash log, …);
- steps or a file that reproduce it;
- the Whiney version or commit.

Expect an acknowledgement within a week. Fixes are released as a new exe,
and the advisory is published once players have had a chance to update.

## Supported versions

Only the latest release and `main` get security fixes.

## Already defended against

These are tested, so a report that breaks one of them is especially welcome:

- archive entries that would land outside their folder, and links, in
  packs and save backups (`util.safe_member_path`);
- downloads that don't match the SHA-256 recorded when the pack was made;
- saves deleted before their safety backup is verified.
