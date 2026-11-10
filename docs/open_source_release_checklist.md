# Open Source Project Release Preflight Checklist

Use this checklist for each public source release and binary release. Check every applicable item, record evidence, and write a reason for each item marked N/A. This is a repeatable maintainer checklist, not legal advice.

## Release Record

- Project and repository:
- Version and release date:
- Git tag and commit:
- Release type: source / binary / both
- Supported platforms and architectures:
- Release assets and SHA-256 values:
- Reviewer and decision: pass / blocked
- Exceptions or follow-up items:

## 1. Source and Version

- [ ] The release tag points to the reviewed commit; the source archive is generated from that tag.
- [ ] The source tree has no unreviewed or uncommitted changes.
- [ ] Tracked and untracked files were inspected. No credentials, private keys, signing certificates, personal data, local absolute paths, machine-specific configuration, caches, virtual environments, or accidental build outputs are included.
- [ ] Version numbers agree across the tag, application metadata, documentation, and release title.
- [ ] A clean checkout can follow the documented build instructions without relying on files from another checkout or the maintainer's machine.

**Pass condition:** the published source can be identified by one immutable tag and commit, and its contents are intentional.

## 2. Ownership and Licensing

- [ ] A license file is present at the repository root and names the license unambiguously.
- [ ] If the project is described as open source, its license is on the OSI-approved list and its terms match the intended permissions and restrictions.
- [ ] The origin and permission status of project code, copied code, data, images, fonts, icons, documentation, and other included assets are known.
- [ ] Every third-party component shipped with a binary was identified at the version actually used. Its license and required notices are recorded in the release materials.
- [ ] License texts and notices required for the chosen distribution are present and correspond to the shipped components.
- [ ] Any source, relinking, written-offer, attribution, or other license-specific condition was checked against the exact license and distribution method. Do not assume that source archives must be embedded in an executable or binary archive.
- [ ] No unresolved ownership, permission, or license conflict remains for release contents.

**Stop condition:** an included component or asset has unknown rights, a required notice is missing, or the planned distribution method has not been checked against an applicable license.

## 3. Build and Dependencies

- [ ] The release build was made from the tagged source in a clean environment using documented tools and dependency versions.
- [ ] Build-time tools and development dependencies are not copied into the runtime package unless the application needs them.
- [ ] The binary's version, platform, architecture, and feature set match the release notes.
- [ ] The build did not silently use stale output, local configuration, or files outside the reviewed source and declared build inputs.
- [ ] Any generated asset or metadata is reproducible from documented inputs, or its provenance is recorded.

**Pass condition:** the binary can be traced to the published source tag and declared build inputs.

## 4. Tests and Runtime Checks

- [ ] The checks appropriate to the change were run, and their results were recorded.
- [ ] The release artifact was installed or extracted on a clean supported environment and launched successfully.
- [ ] The primary user workflows and important file formats were exercised with representative data.
- [ ] Required runtime libraries, plugins, and license notices are present; unused build tools, debug files, samples, and temporary files are absent.
- [ ] Upgrade, configuration, and data migration behavior was checked when applicable.
- [ ] Any known limitations or failures are documented in the release notes.

**Stop condition:** the release cannot be installed or launched on a supported environment, required runtime files are missing, or a release-blocking check failed.

## 5. Artifact Inspection

- [ ] The final source and binary archives were listed and inspected after creation, not inferred from the build folder alone.
- [ ] Unexpected files and directories were investigated; archive contents match the intended deliverables.
- [ ] Artifact size was compared with the previous release. Significant changes were explained by named files or dependencies.
- [ ] The archive contains only runtime files, documentation, and notices needed for that deliverable. Build inputs and source materials are included only when required by the applicable license or intentionally offered as separate release assets.
- [ ] SHA-256 checksums were generated from the final files. Signatures were verified when the project uses signed releases.

**Pass condition:** each large or unusual item in the artifact has a clear purpose, and the published checksum matches the final artifact.

## 6. Repository and Release Page

- [ ] The README explains the project's purpose, current status, supported platforms, basic installation or use, build instructions, and license.
- [ ] Contribution, conduct, support, and security guidance are present when relevant to the project and its community.
- [ ] Issue and pull-request templates are provided when they will help collect useful reports or contributions.
- [ ] The release title, tag, notes, assets, and prerelease status are correct.
- [ ] Release notes state user-visible changes, requirements, installation or upgrade steps, known issues, and links to the source and checksums.
- [ ] Uploaded assets are the final reviewed files; no draft, temporary, or maintainer-only files are attached.
- [ ] GitHub-generated source snapshots are distinguished from separately built source archives and binary assets.

**Note:** GitHub's Community Profile is a recommendation checklist, not a requirement to publish a repository or release.

## 7. Post-Publication Check

- [ ] Download each published asset from the release page and verify its checksum.
- [ ] Install or extract the downloaded binary and repeat the launch smoke check.
- [ ] Confirm the tag, source snapshot, binary assets, release notes, and project links are publicly accessible and refer to the same version.
- [ ] If a published artifact is wrong, replace it only through a clearly documented release correction; update the checksum and notes.

## Release Decision

Mark **PASS** only when all applicable checks pass and every N/A has a reason. Mark **BLOCKED** when source provenance, rights, required notices, build identity, artifact contents, or a release-blocking runtime check is unresolved. Do not publish while blocked.

## Official References

- [GitHub Open Source Guides: Starting an Open Source Project](https://opensource.guide/starting-a-project/)
- [GitHub Docs: Community profiles for public repositories](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)
- [GitHub Docs: Licensing a repository](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
- [GitHub Docs: README files](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
- [GitHub Docs: Contributor guidelines](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/setting-guidelines-for-repository-contributors)
- [GitHub Docs: Code of conduct](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/adding-a-code-of-conduct-to-your-project)
- [GitHub Docs: Security policy](https://docs.github.com/en/code-security/getting-started/adding-a-security-policy-to-your-repository)
- [GitHub Docs: Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [Open Source Initiative: The Open Source Definition](https://opensource.org/osd/)
- [Open Source Initiative: Approved Licenses](https://opensource.org/licenses/)
