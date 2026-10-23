#!/bin/sh
# -----------------------------------------------------------
#  [*] Backend — regression test runner
#
#  Builds the PRODUCTION image (the same python image and pip
#  install that ship — so the build itself must pass first)
#  and runs the unittest suite inside a throwaway container
#  with no network at all: the tests run on FakeWallets and
#  scratch SQLite files, so nothing in them may reach
#  Electrum, a node or the internet, and a connection made by
#  mistake fails at once instead of touching a real chain.
#  No seed is handed in either, so no test can touch real
#  funds. Only the build goes online, for pip; its dependency
#  layer is cached, so once it is in place a run takes seconds
#  and the host needs no python. Extra arguments go to
#  unittest (a module, a class or a test, -k pattern …);
#  without any, the whole suite is discovered.
#
#  The repository's _CONFIG folder (the coins file the app
#  reads its chains from at boot, and the coin logos) is
#  mounted read-only where the app looks for it, so the
#  tests load the configuration that ships.
#
#  The live smoke layer (tests/integration) needs the running
#  backend and stays opt-in; tests/README.md has its command.
# -----------------------------------------------------------
set -e
cd "$(dirname "$0")"

if [ $# -eq 0 ]; then
  set -- discover -t . -s tests
fi

sudo docker build -t knfexchange-backend-check .
sudo docker run --rm --name knfexchange-backend-tests --network none --memory=2g --memory-swap=2g --cpus=2 \
  -v "$(cd .. && pwd)/_CONFIG:/config:ro" \
  knfexchange-backend-check python -m unittest "$@" -v
