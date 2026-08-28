import httpx, json, time, sqlite3

req = 'Renew 100 Microsoft 365 licenses with a budget of PKR 1 million.'
print('Submitting:', req)

resp = httpx.post('http://127.0.0.1:8000/api/workflows', json={'request': req, 'chaos': {}}, timeout=30.0)
data = resp.json()
wid = data.get('id')
print('WORKFLOW ID:', wid)

print('Waiting 5s for workflow to run...')
time.sleep(5)

db = sqlite3.connect('data/orchestrai.db')
c = db.cursor()
c.execute('SELECT entities_json FROM workflows WHERE id = ?', (wid,))
row = c.fetchone()
if row:
    print('DB entities:', row[0])

for step_id in ['s1', 's2', 's3', 's4']:
    c.execute('SELECT output_json FROM steps WHERE workflow_id = ? AND step_id = ?', (wid, step_id))
    row = c.fetchone()
    if row and row[0]:
        try:
            out = json.loads(row[0])
            print(f'DB {step_id} output:', row[0][:200])
            if step_id == 's1': print('  s1 quantity =', out.get('quantity'))
            if step_id == 's4' and 'po' in out: print('  s4 po =', out['po'])
        except Exception as e:
            print(f'DB {step_id} Error:', e)
