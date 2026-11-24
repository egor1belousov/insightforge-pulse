#!/bin/sh
# Lighthouse mobile и desktop по ключевым страницам: ./lighthouse.sh [https://mgtspulse.ru]
BASE=${1:-https://mgtspulse.ru}
OUT=../lighthouse; mkdir -p $OUT
CH=${CHROME_PATH:-$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome | tail -1)}
cookie() { curl -s -o /dev/null -c - "$BASE/demo/$1" | awk '/pulse_session/{print "pulse_session="$7}'; }
HR=$(cookie hr); IN=$(cookie intern)
for spec in "landing|/|" "login|/login|" "dashboard|/dashboard|$HR" "pairs|/pairs|$HR" "forms|/forms|$HR" "me|/me|$IN"; do
  n=${spec%%|*}; rest=${spec#*|}; u=${rest%%|*}; ck=${rest#*|}; H='{}'; [ -n "$ck" ] && H="{\"Cookie\":\"$ck\"}"
  for ff in mobile desktop; do
    PRESET=""; [ "$ff" = desktop ] && PRESET="--preset=desktop"
    CHROME_PATH=$CH npx -y lighthouse@12 "$BASE$u" --quiet $PRESET --chrome-flags="--headless=new --no-sandbox" --extra-headers="$H" --output=json --output-path=$OUT/$n-$ff.json >/dev/null 2>&1
  done
done
