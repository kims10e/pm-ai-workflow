"""PM AI Workflow 개념도 시안 A·B·C 생성기.
실행: python docs/diagrams/gen_diagrams.py [출력 폴더]  (기본: docs/diagrams)
카드 좌표·문구를 고친 뒤 다시 실행하면 HTML 3개가 갱신된다. 화살표는 카드 좌표로 계산된다.
"""
import json, os
import sys
ROOT=sys.argv[1] if len(sys.argv)>1 else 'docs/diagrams'
NAVY='#1F3864'; INK='#14213D'; MUTED='#5B6472'; LINE='#7A828E'; ORANGE='#C2410C'; BLUE='#1D4ED8'; GREEN='#15803D'
FONT="'Noto Sans KR', sans-serif"

class Art:
    def __init__(s,w,h,title):
        s.w,s.h,s.title=w,h,title; s.bg=[]; s.arrows=[]; s.cards=[]; s.labels=[]; s.mk=0
    def band(s,x,y,w,h,fill,border='none',r=12):
        s.bg.append(f'<div style="position: absolute; left: {x}px; top: {y}px; width: {w}px; height: {h}px; box-sizing: border-box; background: {fill}; border: {border}; border-radius: {r}px"></div>')
    def card(s,x,y,w,h,html,fill='#FFFFFF',border=f'1px solid #CBD2DC',color=INK,size=16,align='center',r=10,weight=400,extra=''):
        ja='center' if align=='center' else 'flex-start'
        s.cards.append(f'<div style="position: absolute; left: {x}px; top: {y}px; width: {w}px; height: {h}px; box-sizing: border-box; padding: 12px 16px; display: flex; align-items: center; justify-content: {ja}; text-align: {align}; background: {fill}; border: {border}; border-radius: {r}px; color: {color}; font-size: {size}px; line-height: 1.45; word-break: keep-all; font-weight: {weight}{extra}">{html}</div>')
        return dict(l=x,t=y,r=x+w,b=y+h,cx=x+w//2,cy=y+h//2)
    def label(s,x,y,w,text,size=13,color=MUTED,weight=400,align='center',lh=None):
        lh=lh or int(size*1.3)
        s.labels.append(f'<div style="position: absolute; left: {x}px; top: {y}px; width: {w}px; text-align: {align}; font-size: {size}px; line-height: {lh}px; font-weight: {weight}; color: {color}">{text}</div>')
    def seg(s,x1,y1,x2,y2,head=True,color=LINE,dash=False,name=None,sw=2):
        # straight segment from (x1,y1) to tip (x2,y2)
        h=2*sw if head else 0
        st=f'position: absolute; LEFTTOP width: Wpx; height: Hpx; overflow: visible; fill: none; stroke: {color}; stroke-width: {sw}; stroke-linecap: round; stroke-linejoin: round' + ('; stroke-dasharray: 6 6' if dash else '')
        if y1==y2:
            n=abs(x2-x1); x=min(x1,x2); W,H=n,8; lt=f'left: {x}px; top: {y1-4}px;'
            path=f'M 0 4 L {n-h} 4' if x2>x1 else f'M {n} 4 L {h} 4'
        else:
            n=abs(y2-y1); y=min(y1,y2); W,H=8,n; lt=f'left: {x1-4}px; top: {y}px;'
            path=f'M 4 0 L 4 {n-h}' if y2>y1 else f'M 4 {n} L 4 {h}'
        st=st.replace('LEFTTOP',lt).replace('Wpx',f'{W}px').replace('Hpx',f'{H}px')
        acc=f'role="img" aria-label="{name}"' if name else 'aria-hidden="true"'
        defs=me=''
        if head:
            s.mk+=1; mid=f'dc-arrow-head-filled-{s.mk}'
            defs=f'<defs><marker id="{mid}" orient="auto" markerWidth="5" markerHeight="5" refX="2" refY="2" overflow="visible"><path d="M0 0 L4 2 L0 4 Z" fill="{color}" stroke="none" style="stroke: none; fill: {color}; fill: context-stroke"/></marker></defs>'
            me=f' marker-end="url(#{mid})"'
        s.arrows.append(f'<svg {acc} width="{W}" height="{H}" viewBox="0 0 {W} {H}" preserveAspectRatio="none" style="{st}">{defs}<path d="{path}"{me}></path></svg>')
    def html(s):
        body='\n'.join(s.bg+s.arrows+s.cards+s.labels)
        return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>{s.title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&amp;display=swap">
<style>body{{margin:0;background:#F6F7F9}}</style>
</head>
<body>
<div style="position: relative; width: {s.w}px; height: {s.h}px; background: #F6F7F9; font-family: {FONT}; color: {INK}; overflow: hidden">
{body}
</div>
</body>
</html>
'''

# ---------- A: Executive one-pager ----------
A=Art(1600,1000,'시안 A 임원용 한 장 스토리')
A.label(64,56,1200,'PM AI Workflow',38,INK,700,'left',48)
A.label(64,112,1300,'PM 표준 딜리버리 프로세스를 AI 에이전트로 자동화 — AI가 준비하고, PM이 승인한다',20,MUTED,400,'left',28)
A.band(64,180,360,520,'#EEF1F5'); A.band(480,180,736,520,'#E8EEF8'); A.band(1272,180,264,520,'#EEF1F5')
A.label(88,200,312,'1 · 왜',15,NAVY,700,'left'); A.label(88,222,312,'반복되는 PM 업무의 문제',18,INK,700,'left',24)
A.label(504,200,500,'2 · 어떻게',15,NAVY,700,'left'); A.label(504,222,600,'매주 도는 자동화 루프',18,INK,700,'left',24)
A.label(1296,200,216,'3 · 무엇이 달라지나',15,NAVY,700,'left'); A.label(1296,222,216,'기대 효과',18,INK,700,'left',24)
for i,t in enumerate(['<span><b>수작업 반복</b><br>주간 보고·대장 갱신을 매주 손으로 다시 정리</span>','<span><b>늦게 드러나는 리스크</b><br>메모·회의에 흩어져 보고 시점에야 발견</span>','<span><b>제각각인 산출물</b><br>프로젝트마다 형식·품질이 달라 비교가 어려움</span>']):
    A.card(88,272+i*136,312,112,t,align='left')
c1=A.card(528,288,280,112,'<span><b>① 수집</b><br>주간 메모 입력<br>(텔레그램 또는 직접 실행)</span>')
c2=A.card(888,288,280,112,'<span><b>② 분석</b><br>리스크·이슈·액션·변경<br>자동 추출</span>',fill='#EAF0FF',border=f'1px solid {BLUE}')
c3=A.card(888,480,280,112,'<span><b>③ 초안</b><br>주간 보고서 · RAG ·<br>OKR 진척 자동 생성</span>',fill='#EAF0FF',border=f'1px solid {BLUE}')
c4=A.card(528,480,280,112,'<span><b>④ 승인</b><br>PM이 검토 후 확정<br>승인 없이는 반영 안 함</span>',fill='#FFF4EC',border=f'2px solid {ORANGE}')
A.seg(c1['r'],c1['cy'],c2['l']-1,c2['cy'],name='수집에서 분석으로')
A.seg(c2['cx'],c2['b'],c2['cx'],c3['t']-1,name='분석에서 초안으로')
A.seg(c3['l'],c3['cy'],c4['r']+1,c3['cy'],color=ORANGE,name='초안에서 승인으로, 검토 요청')
A.seg(c4['cx'],c4['t'],c4['cx'],c1['b']+1,name='승인 후 다음 주 수집으로')
A.label(812,c3['cy']-28,72,'검토 요청',13,ORANGE,500)
A.label(c4['cx']+12,(c1['b']+c4['t'])//2-8,80,'다음 주',13,MUTED,500,'left')
A.card(528,624,640,56,'<span><b>Project Workbook</b> · 액션 · 리스크 · 이슈 · 변경 · OKR — 모든 단계가 읽고 쓰는 단일 기준</span>',fill='#FFFFFF',border=f'1px dashed {NAVY}',size=14)
for i,t in enumerate(['<span><b>보고 준비 부담 감소</b><br>메모 한 번으로 대장·보고 동시 갱신</span>','<span><b>리스크 조기 경보</b><br>주간 메모에서 즉시 추출·표시</span>','<span><b>표준 품질</b><br>보고서 형식과 점검 규칙을 고정</span>']):
    A.card(1296,272+i*136,216,112,t,align='left',size=15)
A.label(64,740,600,'통합 딜리버리 단계 (P0 → P5)',15,NAVY,700,'left')
ph=[('P0','수주·인수인계'),('P1','착수'),('P2','계획'),('P3','수행·통제'),('P4','인수·이관'),('P5','종료')]
for i,(k,v) in enumerate(ph):
    x=64+i*248
    if k=='P3':
        A.card(x,772,224,88,f'<span><b>{k} {v}</b><br>실제 시연 범위</span>',fill=NAVY,border=f'1px solid {NAVY}',color='#FFFFFF',size=15)
    elif k in('P0','P1'):
        A.card(x,772,224,88,f'<span><b>{k} {v}</b><br>구현 완료</span>',border=f'1px solid {NAVY}',size=15)
    else:
        A.card(x,772,224,88,f'<span><b>{k} {v}</b><br>설계 제시</span>',border='1px dashed #9AA3AF',color=MUTED,size=15)
    if i<5: A.seg(x+224,816,x+247,816,head=True,name=f'{k}에서 다음 단계로')
A.label(64,900,1472,'Personal project, built outside the work network · 모든 데이터는 가상 고객 사례',13,MUTED,400,'left')

# ---------- B: Practitioner swimlane ----------
B=Art(1600,1000,'시안 B 실무자용 스윔레인')
B.label(64,56,1300,'실무자용 — 주간 루프 스윔레인 (P3 수행·통제)',30,INK,700,'left',40)
B.label(64,104,1400,'누가 · 무엇을 · 어떤 순서로: 메모 한 건이 승인된 보고서와 갱신된 Workbook이 되기까지',17,MUTED,400,'left',24)
lanes=['PM','입력 채널','오케스트레이터','Claude 스킬','Project Workbook','산출물']
subs=['폰 · PC','Telegram(선택) · CLI','pm_agent.py','claude -p','CSV 단일 기준','docx · md']
LT=[200+i*112 for i in range(6)]
for i,(t,sb) in enumerate(zip(lanes,subs)):
    B.band(64,LT[i],1472,112,'#FFFFFF' if i%2==0 else '#EEF1F5',r=0)
    B.label(80,LT[i]+34,160,t,16,INK,700,'left',22); B.label(80,LT[i]+58,160,sb,12,MUTED,400,'left',16)
def bc(lane,col,html,**k):
    # 카드 안 줄바꿈은 <br>로 직접 지정한다(한글이 단어 중간에서 끊기지 않도록)
    return B.card(248+col*186,LT[lane]+14,150,84,html,size=13,extra='; padding: 6px 8px',**k)
b1=bc(0,0,'<span><b>①</b> 주간 메모 작성</span>')
b2=bc(1,1,'<span><b>②</b> 메모 수신<br>등록된 본인만 허용</span>')
b3=bc(2,2,'<span><b>③</b> 메모 · Workbook<br>읽기</span>')
b4=bc(3,3,'<span><b>④</b> 변경안 추출<br>risk-update<br>+ 규칙 검증</span>',fill='#EAF0FF',border=f'1px solid {BLUE}')
b5=bc(3,4,'<span><b>⑤</b> 보고서 초안<br>status-report</span>',fill='#EAF0FF',border=f'1px solid {BLUE}')
b6=bc(2,5,'<span><b>⑥</b> 승인 요청<br>변경 미리보기<br>Telegram · 터미널</span>',fill='#FFFFFF',border=f'1px solid {NAVY}')
b7=bc(0,6,'<span><b>⑦</b> 승인 / 반려<br>사람이 결정</span>',fill='#FFF4EC',border=f'2px solid {ORANGE}')
b8=bc(4,6,'<span><b>⑧</b> 확정 반영<br>변경 이력 기록</span>')
b9=bc(5,6,'<span><b>⑨</b> 확정본 저장<br>report.docx · md</span>',fill='#EAF7EF',border=f'1px solid {GREEN}')
# 흐름 밖의 별도 실행: Quality Gate는 quality 명령으로 따로 돌린다(승인 흐름에 자동 연결되지 않음)
bq=bc(2,4,'<span><b>Quality Gate</b><br>별도 명령(quality)<br>누락 · 지연 점검</span>',fill='#FFFFFF',border='1px dashed #9AA3AF',color=MUTED)
def bent_down(a,b,name,color=LINE):
    B.seg(a['r'],a['cy'],b['cx'],a['cy'],head=False,color=color,name=None)
    B.seg(b['cx'],a['cy'],b['cx'],b['t']-1,color=color,name=name)
bent_down(b1,b2,'메모 작성에서 수신으로')
bent_down(b2,b3,'수신에서 단계 판별로')
bent_down(b3,b4,'Workbook 읽기에서 변경안 추출로')
B.seg(b4['r'],b4['cy'],b5['l']-1,b5['cy'],name='변경안 추출에서 보고서 초안으로')
B.seg(b5['r'],b5['cy'],b6['cx'],b5['cy'],head=False)
B.seg(b6['cx'],b5['cy'],b6['cx'],b6['b']+1,name='보고서 초안에서 승인 요청으로')
B.seg(b6['cx'],b6['t'],b6['cx'],b7['cy'],head=False,color=ORANGE)
B.seg(b6['cx'],b7['cy'],b7['l']-1,b7['cy'],color=ORANGE,name='승인 요청에서 사람의 승인 또는 반려로')
B.label(b6['cx']+12,(b6['t']+b7['cy'])//2-8,80,'승인 요청',13,ORANGE,500,'left')
B.seg(b7['cx'],b7['b'],b7['cx'],b8['t']-1,color=GREEN,name='승인 시 Workbook 확정 반영으로')
B.label(b7['cx']+12,(b7['b']+b8['t'])//2-8,48,'승인',13,GREEN,500,'left')
B.seg(b8['cx'],b8['b'],b8['cx'],b9['t']-1,color=GREEN,name='확정 반영에서 확정본 저장으로')
B.card(860,LT[0]+14,360,84,'<span><b>반려하면 확정하지 않습니다</b><br>승인 전 결과는 drafts에만 남고,<br>다시 반영하려면 새로 실행합니다</span>',fill='#FFFFFF',border=f'1px dashed {ORANGE}',size=13,align='left',extra='; padding: 6px 12px')
B.label(64,896,1472,'파랑 = AI 생성 · 주황 = 사람 승인 경로 · 초록 = 확정 · 회색 점선 = 흐름에 자동 연결되지 않는 별도 실행',13,MUTED,400,'left')
B.label(64,918,1472,'가상 데이터 · personal project built outside the work network',13,MUTED,400,'left')

# ---------- C: Lifecycle + engine ----------
C=Art(1600,1040,'시안 C 단계별 자동화 지도')
C.label(64,56,1300,'딜리버리 전 과정의 자동화 지도 — 어디에, 무엇을, 어디까지',30,INK,700,'left',40)
C.label(64,104,1200,'위: 프로젝트 단계와 게이트 · 가운데: 단계별 AI 스킬 · 아래: 공통 엔진과 효과',17,MUTED,400,'left',24)
C.card(1112,96,424,48,'<span>■ 시연 범위  □ 구현 완료  ┅ 설계 제시</span>',fill='#FFFFFF',border='1px solid #CBD2DC',size=13)
P=[('P0','수주·인수인계','G0 Handover','sow-intake','범위·가정·리스크 추출','impl'),
   ('P1','착수','G1 범위·OKR 합의','charter-okr','Charter·공동 OKR 초안','impl'),
   ('P2','계획','G2 합의 후 Kickoff','meeting-minutes','회의록·웨이브 계획','design'),
   ('P3','수행·통제','G3 마일스톤 리뷰','status-report<br>risk-update','주간 보고·리스크 경보','demo'),
   ('P4','인수·이관','G4 고객 인수 서명','acceptance-check','인수시험 체크리스트','design'),
   ('P5','종료','G5 협의 후 종료','closing-report','완료 보고·교훈','design')]
eng=None
for i,(k,v,g,sk,sd,st) in enumerate(P):
    x=64+i*254
    if st=='demo': pf,pb,pc=NAVY,f'1px solid {NAVY}','#FFFFFF'; sf,sb_=('#EAF0FF',f'2px solid {BLUE}')
    elif st=='impl': pf,pb,pc='#FFFFFF',f'1px solid {NAVY}',INK; sf,sb_=('#FFFFFF',f'1px solid {BLUE}')
    else: pf,pb,pc='#FFFFFF','1px dashed #9AA3AF',MUTED; sf,sb_=('#FFFFFF','1px dashed #9AA3AF')
    p=C.card(x,184,200,112,f'<span><b>{k} {v}</b><br>{g}</span>',fill=pf,border=pb,color=pc,size=15)
    s=C.card(x,392,200,112,f'<span><b>{sk}</b><br>{sd}</span>',fill=sf,border=sb_,size=14,color=INK if st!='design' else MUTED)
    if i<5: C.seg(x+200,240,x+253,240,name=f'{k}에서 다음 단계로')
    C.seg(p['cx'],p['b'],p['cx'],s['t']-1,color='#9AA3AF',name=f'{k} 단계에서 {sk} 스킬로')
    C.seg(s['cx'],s['b'],s['cx'],599,color='#9AA3AF',name=f'{sk} 스킬에서 공통 엔진으로')
C.label(64,336,300,'단계별 AI 스킬',14,NAVY,700,'left')
C.card(64,600,1470,136,'<span><b style="font-size:18px">공통 엔진</b><br>오케스트레이터(pm_agent.py) · Claude 스킬 · Project Workbook(액션·리스크·이슈·변경·OKR 단일 기준) · Quality Gate · 사람 승인 후 확정 · 변경 이력</span>',fill='#FFFFFF',border=f'2px solid {NAVY}',size=15)
vals=[('임원 관점','주간 RAG·OKR 진척을 한 장으로 — 의사결정에 필요한 신호만'),('실무 관점','메모 한 번으로 대장·보고·액션 동시 갱신 — 반복 작업 제거'),('통제 관점','사람 승인과 변경 이력 — 누가, 언제, 무엇을 확정했는지 추적')]
for i,(t,d) in enumerate(vals):
    C.card(64+i*506,792,458,112,f'<span><b>{t}</b><br>{d}</span>',fill='#EEF1F5',border='1px solid #CBD2DC',size=15,align='left')
C.label(64,944,1472,'Personal project, built outside the work network · 모든 데이터는 가상 고객 사례',13,MUTED,400,'left')

os.makedirs(ROOT,exist_ok=True)
for n,a in [('concept_A_executive.html',A),('concept_B_swimlane.html',B),('concept_C_map.html',C)]:
    open(os.path.join(ROOT,n),'w',encoding='utf-8').write(a.html())
print('ok')
