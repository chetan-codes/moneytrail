import hashlib
import math

COLORS = {'sender': '#65e0cc', 'processor': '#b59bff', 'recipient': '#6eaaff'}
CENTERS = {'sender': (-8, 0), 'processor': (0, 0), 'recipient': (8, 0)}


def org_nodes():
    return [dict(id='org:'+org,label={'sender':'NORTHSTAR / SENDER','processor':'MERIDIAN / PROCESSOR','recipient':'HARBOR / RECIPIENT'}[org],
                 organization=org,kind='organization',x=xy[0],y=xy[1],size=14,color=COLORS[org]) for org,xy in CENTERS.items()]


def evidence_node(record, index):
    org = record['organization']
    x,y = CENTERS[org]
    angle = index * 2.399963
    return dict(id=record['id'],label=record['title'],kind=record['kind'],organization=org,
                x=x+math.cos(angle)*2.1,y=y+math.sin(angle)*2.1,size=7,
                color='#eacb80' if record['kind'] in ('agreement','amendment') else COLORS[org],
                evidence_id=record['id'],amount_minor=record.get('amount_minor'))


def overview(records):
    nodes = [org_nodes()[0]]
    edges = []
    counterparties = {}
    paid = {}
    for r in records:
        count, total = paid.get(r['metadata']['counterparty'], (0, 0))
        paid[r['metadata']['counterparty']] = (count + 1, total + r['amount_minor'])
    for i,r in enumerate(records):
        name=r['metadata']['counterparty']
        if name not in counterparties:
            j=r['metadata']['counterparty_id']; angle=j*2.399963
            count,total=paid[name]
            # Hovering a node in the history should say what it is, not just name it.
            node=dict(id='counterparty:'+str(j),label=f'{name} · {count} past payments · USD {total/100:,.2f} in total',kind='counterparty',organization='sender',
                      x=math.cos(angle)*(4+j%7),y=math.sin(angle)*(4+j%7),size=4,color='#447b85',background=True)
            counterparties[name]=node
            nodes.append(node)
        center=counterparties[name]
        digest=int(hashlib.sha256(r['id'].encode()).hexdigest()[:8],16)
        angle=(digest%10000)/10000*math.tau; radius=.2+(digest%300)/180
        nodes.append(dict(id=r['id'],label=f"Past payment · USD {r['amount_minor']/100:,.2f} to {name} · {r['timestamp'][:10]} · {r['reference']}",kind='transaction',organization='sender',
                          x=center['x']+math.cos(angle)*radius,y=center['y']+math.sin(angle)*radius,
                          size=1.7,color='#284d5a',evidence_id=r['id'],amount_minor=r['amount_minor'],background=True))
        edges.append(dict(id='history:'+r['id'],source=r['id'],target=center['id'],kind='money'))
    return dict(nodes=nodes,edges=edges)
