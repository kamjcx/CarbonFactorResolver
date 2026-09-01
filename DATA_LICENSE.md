# Data License and Provenance

The MIT code license does not grant rights to third-party emission-factor data.

## Included public data

Files shipped under `data/benchmarks/` and `data/fixtures/` are small, project-authored,
public-synthetic QA fixtures. Names, identifiers, values, locators and hashes are fictional and
exist only to exercise retrieval and qualification behavior. `example.invalid` locators are
non-resolving by design. They are distributed under the repository MIT license.

Some tests and source-priority rules mention third-party provider names or database versions to
exercise metadata handling. Those labels do not contain, reproduce, or license the named
provider's database content.

## Excluded data

This repository, package, Docker image and release assets must not contain:

- ecoinvent or other licensed database exports, datasets, bulk factor values, or reconstructable
  derivatives;
- customer documents, enterprise catalogues, calculation snapshots, or private evidence;
- API keys, database credentials, licence files, or authenticated source responses.

Users must supply lawful structured adapters and comply with each provider's terms. In
particular, an ecoinvent subscription or developer/enterprise licence may be required for a
deployment that integrates ecoinvent data. CFR provides interfaces, not redistribution rights.

## Release control

Public-release tests inventory packaged JSON/JSONL fixtures, reject database/archive/office
files, and inspect package members. Security reporting is described in [SECURITY.md](SECURITY.md).

