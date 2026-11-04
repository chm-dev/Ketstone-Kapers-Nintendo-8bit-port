# Re-checks the python reference models against the golden Altirra traces (no emulator needed).
$ErrorActionPreference = 'Continue'
$fail = 0
function Run($label, $args_) {
    $out = python -I @args_ 2>&1
    $last = ($out | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0) { $script:fail++ }
    "{0,-12} {1}" -f $label, $last
}
Run 'kop_a'   @('tests/test_kk_model.py','tests/golden/kop_a.txt','right:100,left:60,fire:2,centre:30,left+fire:45,right+fire:45,down:15,left+down:15,left:75,centre:20','--old')
Run 'kop_b'   @('tests/test_kk_model.py','tests/golden/kop_b.txt','left:90,right:30,right:100,fire:3,left+fire:40,down:5,left:30','--old')
Run 'esc0'    @('tests/test_kk_model.py','tests/golden/kop_esc.txt','left:200,right:60,left:40','--init=screen=7,path=7,x0=B0')
Run 'esc1'    @('tests/test_kk_model.py','tests/golden/kop_esc1.txt','right:200,left:20','--init=screen=0,path=0F,x1=50,c1c=20')
Run 'esc2'    @('tests/test_kk_model.py','tests/golden/kop_esc2.txt','left:200,right:20','--init=screen=7,path=17,x2=B0,c1c=40')
Run 'elev_a'  @('tests/test_elevator.py','tests/golden/elev_a.txt','centre:10,up:5,centre:400,down:5,centre:30,right:30,centre:10','--init=screen=4,path=4,e8e=E0,e6b=0,x0=78')
Run 'elev_b'  @('tests/test_elevator.py','tests/golden/elev_b.txt','centre:10,up:150,centre:20,down:100','--init=screen=4,path=4,e8e=80,e6b=0,x0=78')
Run 'thief'   @('tests/test_thief_model.py','tests/golden/thief_idle.txt')
& python -I tools/obstacle_model.py | Out-Null; if ($LASTEXITCODE -ne 0) { $fail += ' obstacle' }
if ($fail) { "FAILED: $fail"; exit 1 } else { 'all models match' }
