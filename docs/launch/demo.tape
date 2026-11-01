# vhs tape: a real brain-core session, rendered to docs/img/demo.gif
#   brew install vhs && vhs docs/launch/demo.tape
# Runs for real against a temp agent and the local Hindsight (bank demo-brain).

Output docs/img/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 640
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms
Set Padding 18

Hide
Type "export PATH=$HOME/Projects/brain-core/.venv/bin:$PATH; rm -rf /tmp/demo; mkdir -p /tmp/demo; cd /tmp/demo; clear"
Enter
Show

Type "brain init Atlas --path ./Atlas --user Alex"
Sleep 600ms
Enter
Sleep 2s

Type "brain doctor ./Atlas"
Sleep 600ms
Enter
Sleep 4s

Type "clear"
Enter
Type "python ~/Projects/brain-core/docs/launch/demo_session.py ./Atlas/brain.yaml"
Sleep 600ms
Enter
Sleep 26s
