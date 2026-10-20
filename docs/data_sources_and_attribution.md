# Data sources, licensing and attribution

Original SentinelPOMDP material: **Copyright 2026 AdnanSherwani2003**, offered under
[Apache-2.0](../LICENSE); see [NOTICE](../NOTICE). The owner explicitly confirmed
this GitHub username as the preferred copyright-holder identifier. No legal name,
ownership of third-party work, or Apache Software Foundation affiliation is asserted.
The generic copyright example in the official license appendix is not a filled-in
project ownership statement. No existing third-party notices have been removed.

## Olist research data — not redistributed

Source: **Brazilian E-Commerce Public Dataset by Olist**, published by **Olist**
on [Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).
Kaggle's [primary metadata](https://www.kaggle.com/api/v1/datasets/view/olistbr/brazilian-ecommerce),
checked 2026-10-20, lists **CC BY-NC-SA 4.0**. Refer to the
[license terms](https://creativecommons.org/licenses/by-nc-sa/4.0/) and the
publisher's current dataset information before use.

SentinelPOMDP uses the separately obtained dataset for non-commercial research
and teaching. Original files are not bundled in Git, wheels, source distributions
or the default synthetic demonstration. Obtain them from the publisher yourself.
The code license does not relicense Olist data or grant additional rights over it.

Public research material is limited to reviewed aggregate statistics, evaluation
metrics, methodology and source-file hashes. Local imports, original CSV rows,
operational traces, raw-row screenshots and data-derived candidate model weights
remain private in this release proposal. Reports describe filtering, date comparison
and chronological evaluation rather than presenting modified records as originals.
No approval to redistribute raw files or to use Olist commercially is implied.

## Synthetic examples

Supplier-delay, security-simulator, representative-pilot and procurement examples
are explicitly synthetic engineering fixtures, not customer documents or verified
business outcomes. Their generators are included in source; they require no Olist
archive, external model key or private operational store.

## Dependencies and tooling

Python dependencies are declared in pyproject.toml and locked in uv.lock. The
optional diagram checker uses Mermaid and jsdom, pinned in
tools/diagrams/package.json and package-lock.json. These projects retain their
own copyrights and licenses. Dependencies are installed from package registries;
their code, virtual environments and node_modules are not vendored into Git.
Installed upstream license/notice files must be retained when distributing those
dependencies or container images. No blanket Apache ownership claim is made for
third-party packages. UI styling uses system fonts; no downloaded font files or
external icon bundle is included.
