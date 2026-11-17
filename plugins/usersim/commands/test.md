---
description: User-test a web product with a plain tester and 2-3 simulated user groups in parallel, then replay the runs and propose fixes where the groups diverge
argument-hint: "[product URL] [task, optional] [competitor URLs, optional]"
---
Run the `usertest` skill from this plugin on: $ARGUMENTS

If no URL is given, find the product's public or preview URL from this repository (README, deploy config, package.json homepage) and ask the user to confirm it. Localhost is not reachable from the cloud browsers.
