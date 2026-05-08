# SignalBridge for openFDA

[![SafeSkill 50/100](https://img.shields.io/badge/SafeSkill-50%2F100_Use%20with%20Caution-orange)](https://safeskill.dev/scan/janiumang-mcp-server-openfda)
SignalBridge for openFDA is an experimental Model Context Protocol server that allows AI assistants to query public FDA datasets for pharmacovigilance research workflows.

It connects to openFDA APIs and exposes structured tools for:
- FAERS adverse event exploration
- FDA drug label lookup
- label listedness checks
- drug recall/enforcement searches
- query audit trails and source transparency

Example question:

**What is the public FDA safety profile of pembrolizumab in patients over 65 during the last 5 years?**

This project is designed to demonstrate how domain-specific AI tools can make complex public regulatory datasets more accessible while preserving important safety, causality, and data-quality caveats. It is not a validated pharmacovigilance system, medical device, regulatory decision engine, or replacement for qualified safety/medical review.
