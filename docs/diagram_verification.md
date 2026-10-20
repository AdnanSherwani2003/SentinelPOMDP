# Diagram verification

The optional checker parses the Mermaid blocks in README.md and
docs/architecture.md. It does not render a browser page or prove GitHub's current
renderer accepts every diagram. The application needs neither Node.js nor these
tools at runtime.

Use Node.js 22.12 or newer with npm, from the repository root:

```powershell
npm ci --prefix tools/diagrams --include=dev --ignore-scripts
npm run --prefix tools/diagrams check
```

Mermaid and jsdom have exact direct versions in tools/diagrams/package.json;
package-lock.json pins the dependency graph and integrity hashes. `npm ci` installs
that lockfile rather than re-resolving versions. Lifecycle scripts are disabled.
No existing dependency directory under data/ is used. node_modules is ignored and
must not be staged. Dependencies keep their upstream license/notice files.

The equivalent check after installation is `node scripts/validate_diagrams.mjs`.
The script resolves paths relative to itself, not the caller's working directory.
Success reports the number of parsed blocks; malformed diagrams cause nonzero
exit. Check [release validation](release_validation.md) for actual verification
results. Remote rendering and remote CI are separate, unverified steps until an
owner-authorized publication/run occurs.
