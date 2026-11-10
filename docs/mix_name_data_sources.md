# MIX Name Data Sources

The browser can use the bundled XCC name source and an optional CnCNet community database. Each resolved entry keeps the source label so it can be inspected in the entry tooltip.

## XCC Name Lists

- Files: `mix_browser/data/name_sources/xcc/td mix description.txt`, `ts mix description.txt`, and `ra2 mix description.txt`
- Project: [XCC Utilities](https://github.com/OlafvdSpek/xcc)
- Source files: [TD MIX description list](https://github.com/OlafvdSpek/xcc/blob/master/data/td%20mix%20description.txt), [TS MIX description list](https://github.com/OlafvdSpek/xcc/blob/master/data/ts%20mix%20description.txt), and [RA2 MIX description list](https://github.com/OlafvdSpek/xcc/blob/master/data/ra2%20mix%20description.txt)
- License: GPL-3.0, included with the project as `mix_browser/data/name_sources/xcc/COPYING`
- XCC TD rows put the filename before a tab and a human-readable description after it; only the filename field is used as a hash candidate.
- XCC's current data directory does not provide a separate Red Alert list. Red Alert names can come from the optional community database.

## Community Global MIX Database Update

- Downloaded file: `name-sources/community/global_mix_database.dat.zip` beside the application
- Original attachment: [`global_mix_database.dat.zip`](https://forums.cncnet.org/applications/core/interface/file/attachment.php?id=40719)
- Forum post: [updated global mix database](https://forums.cncnet.org/topic/2286-updated-global-mix-database/)
- Contributor: Blade, CnCNet Community Forums
- Database timestamp: 2015-04-13
- The database is not included in application releases. A user can request a direct download from the CnCNet attachment in Preferences; the validated archive is stored beside the application and only enabled as a name source after download.
- The community source is disabled by default. CLI and MCP can request the same download through `mix-browser-cli name-source download-community` and the `download_community_name_database` tool. Both use the archive application API; neither starts a download automatically. Pass `--community-names` to enable the downloaded source for CLI or MCP.
- The archive contains four groups in order: TD (`Database 1`), RA (`Database 2`), TS (`Database 3`), and RA2/YR (`Database 4`). The Game menu selects the group used for name inference. The post and attachment do not state a separate license. Attribution records the source and contributor, but does not itself grant permission. The download flow avoids redistributing the community archive with the application; it does not establish a license for other redistribution or use.

The old `known_resource_names.json` corpus has been removed. Names discovered beside the archive and in embedded local MIX databases remain available regardless of these source settings.
