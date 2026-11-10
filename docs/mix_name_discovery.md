# MIX Name Discovery

The browser resolves MIX entry names from the opened archive's embedded local database, configured name lists, and names learned from archives opened during the current application session. It does not scan the archive's containing directory or attempt to invert MIX hashes.

## Candidate Sources

- Names from `local mix database.dat` embedded in the opened MIX archive.
- The bundled XCC name lists for Tiberian Dawn (TD), Tiberian Sun (TS), and Red Alert 2/Yuri's Revenge (RA2/YR), plus the optional downloaded community Global MIX Database. The Game dialog selects which game's list is used and shows the current name-source availability. This selection affects MIX hash-to-name candidates only; it does not switch palette automation or the configured game directory. XCC does not provide a separate Red Alert (RA) list in its data directory, so RA inference uses the community database when it is downloaded and enabled. CLI and MCP callers can choose `td`, `ra`, `ts`, or `ra2yr` for archive inspection, recursive search, and archive-entry preview. Source and license details are recorded in [`mix_name_data_sources.md`](mix_name_data_sources.md); source toggles remain in Preferences > MIX Name Sources.
- Names already resolved in another archive opened during the current application session.

The embedded local database is read from the MIX currently being opened. No sibling files, text configuration, Art INI files, or neighboring MIX archives are scanned for candidate names. Name matching and archive opening run through the application's serial background executor so the in-memory name catalog has a single writer.

Double-clicking an entry recognized as a MIX archive opens it in a new tab. The browser parses the nested archive directly from its bounded byte range in the containing MIX, without extracting a temporary copy. Double-clicking another entry copies it in chunks to a uniquely named temporary directory and asks the operating system to open that file with its default application. The browser monitors opened copies and offers to update the MIX when their contents change. Updating rebuilds the entry table and nested MIX parents, so files can grow or shrink without leaving stale data in the archive. Temporary copies remain available for the application session and are cleaned up when the browser exits; a file still held open by another application may remain in the system temporary directory.

## Matching And Evidence

Each candidate is hashed with the supported MIX hash functions and compared with the archive's entry IDs. Names that produce multiple distinct candidate identities for an entry remain unresolved. MIX hashes fold case, so candidates differing only by letter case are treated as the same hash identity; the displayed spelling comes from the first collected source.

Resolved rows expose their source in the name tooltip. Embedded local database entries, configured name lists, and names learned from previously opened archives are labeled separately. These sources establish why a name was considered; they do not guarantee that every archived ID has a recoverable filename. File signatures may identify a resource type but cannot establish its original basename.

When an entry has no resolved filename, the Type column uses bounded content signatures for formats such as MIX, INI/text, common images, audio/video containers, and PE executables. The standard `mimetypes` module cannot identify nameless archive entries because it relies on a filename extension. Formats without a reliable supported signature remain `Unknown`.

The bundled XCC list and downloaded community database are optional candidate sources. The opened MIX's embedded local database and names learned during the current application session remain available regardless of the name-source settings. Unresolved entries remain unknown instead of being filled from an unverified list.
