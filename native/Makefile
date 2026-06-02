# Makefile for macfan_smc
# MacFanControl - Lightweight SMC helper for MacBookPro11,5
#
# Requirements:
#   - Xcode Command Line Tools (xcode-select --install)
#   - macOS with IOKit framework (standard on all Macs)
#
# Usage:
#   make          - build the binary
#   make clean    - remove build artifacts
#   make check    - verify clang and IOKit are available before building

CC      = clang
BINARY  = macfan_smc
SRC     = macfan_smc.c

# -DCMD_TOOL_BUILD  : enables the command-line sections in smc.c
#                     (smc_init, smc_close, SMCReadKey, SMCWriteKey, etc.)
# -framework IOKit  : required for AppleSMC kernel extension access
# -framework CoreFoundation : required by IOKit
# -Wall             : show all warnings (good to know about, not fatal)
# -O2               : light optimization, keeps binary small and fast
CFLAGS  = -DCMD_TOOL_BUILD -Wall -O2
LDFLAGS = -framework IOKit -framework CoreFoundation

.PHONY: all clean check

all: $(BINARY)

$(BINARY): $(SRC) smc.c smc.h
	$(CC) $(CFLAGS) $(LDFLAGS) -o $(BINARY) $(SRC)
	@echo "Build successful: ./$(BINARY)"

clean:
	rm -f $(BINARY)

check:
	@echo "Checking build environment..."
	@command -v clang >/dev/null 2>&1 && echo "  clang: OK" || echo "  clang: NOT FOUND - run: xcode-select --install"
	@test -d /System/Library/Frameworks/IOKit.framework && echo "  IOKit: OK" || echo "  IOKit: NOT FOUND"
	@test -f smc.c && echo "  smc.c: OK" || echo "  smc.c: NOT FOUND - copy from smcFanControl/smc-command/"
	@test -f smc.h && echo "  smc.h: OK" || echo "  smc.h: NOT FOUND - copy from smcFanControl/smc-command/"