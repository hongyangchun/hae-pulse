#!/opt/homebrew/bin/python3
# <xbar.title>HAE Pulse</xbar.title>
# <xbar.version>0.1.0</xbar.version>
# <xbar.author>hongyangchun</xbar.author>
# <xbar.desc>Health recovery pulse: HRV vs 7-day baseline with recovery verdict, sleep, weight, exercise and a 7-day training log, read from the Health Auto Export cloud feed. macOS port of omarchy-hae-pulse.</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <xbar.abouturl>https://github.com/hongyangchun/hae-pulse</xbar.abouturl>
#
# Hide SwiftBar's own entry at the top of this plugin's dropdown. The default
# menu bar icon is separate and is suppressed via the StealthMode preference
# (see README, "隐藏 SwiftBar 自身"). Option+Click reveals the hidden items.
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
#
# Thin SwiftBar shim: the real work lives in ../render.py, which drives the
# shared ../collector.py. Kept separate so SwiftBar's plugin folder contains
# only executable plugins.

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import render  # noqa: E402

if __name__ == "__main__":
    render.main()
