# vhs tape: a real brain-core session, rendered to docs/img/demo.gif
#   brew install vhs && vhs docs/launch/demo.tape
# Runs for real against a throwaway lite agent (no Hindsight needed) in /tmp/brain-demo, with HOME
# pointed there too so no real path or user name is recorded. Run it from the repo root; it uses
# the repo's .venv. Afterwards: rm -rf /tmp/brain-demo

Output docs/img/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 640
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Padding 18

Hide
Type "export REPO=$PWD PATH=$PWD/.venv/bin:$PATH DEMO_PAUSE=1.6; rm -rf /tmp/brain-demo; mkdir -p /tmp/brain-demo/home; cd /tmp/brain-demo; export HOME=/tmp/brain-demo/home; clear"
Enter
Show

Type "brain init Atlas --path ./Atlas --user Alex --lite"
Sleep 600ms
Enter
Sleep 2s

Type "brain doctor ./Atlas"
Sleep 600ms
Enter
Sleep 4s

Type "clear"
Enter
Type "python $REPO/docs/launch/demo_session.py ./Atlas/brain.yaml"
Sleep 600ms
Enter
Sleep 16s
