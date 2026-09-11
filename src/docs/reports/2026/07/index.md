---
month: JULY
year: 2026
excerpt: Maven Artifact plugin buildinfo work for reproducible builds, Surefire 3.6.0-M2 and Maven 3.10.0-rc-1, settings aliases and Plexus plugin DI, and documentation architecture
contributors:
  - https://github.com/slawekjaranowski
  - https://github.com/Ndacyayisenga-droid
  - https://github.com/sparsick
  - https://github.com/sebtiem
  - https://github.com/olamy
---

# July 2026

## Security of the Supply Chain

- type: IMPROVEMENT
  text: Analyze Maven Artifact plugin to make improvements for buildinfo generation and build comparison in context of reproducible builds
  link: https://github.com/support-and-care/maven-support-and-care/issues/242

## Maintenance

- type: BUG_FIX
  text: Fix issues of new Surefire mode using JUnit Platform only; prepare new release 3.6.0-M2
  link: https://github.com/support-and-care/maven-support-and-care/issues/246

- type: MAINTENANCE
  text: Prepare to upgrade Release Drafter from version 6.x to 7.x
  link: https://github.com/support-and-care/maven-support-and-care/issues/241

- type: MAINTENANCE
  text: Test Maven 3.10.0 and fix reported issues
  link: https://github.com/support-and-care/maven-support-and-care/issues/211

- type: MAINTENANCE
  text: Support the release of Maven 3.10.0-rc-1
  link: https://github.com/support-and-care/maven-support-and-care/issues/211

## Modernization of Core Features

- type: FEATURE
  text: Add support for aliases in servers in Maven settings.xml
  link: https://github.com/support-and-care/maven-support-and-care/issues/211

- type: FEATURE
  text: Add validation for Plexus-based plugin dependency injection in Maven plugins
  link: https://github.com/support-and-care/maven-support-and-care/issues/211

## Documentation

- type: DOCUMENTATION
  text: Enable a writing guide
  link: https://github.com/support-and-care/doc-for-maven/issues/12

- type: DOCUMENTATION
  text: Start working on an information architecture
  link: https://github.com/support-and-care/doc-for-maven/issues/13

- type: DOCUMENTATION
  text: Start writing a chapter about adding and excluding dependencies
  link: https://github.com/support-and-care/doc-for-maven/issues/18

- type: DOCUMENTATION
  text: Start writing a chapter about the dependency mechanism
  link: https://github.com/support-and-care/doc-for-maven/issues/19
