import {test} from 'node:test';
import assert from 'node:assert/strict';
import {environment, request} from './harness.js';

async function room() {
  const harness = environment();
  const result = await harness.fetch(request('/rooms', {method: 'POST'}));
  assert.equal(result.status, 201);
  const data = await result.json();
  const call = (path, options = {}) => harness.fetch(request(`/rooms/${data.id}/${path}`, {...options, headers: {'X-Room-Key': data.key, ...options.headers}}));
  return {...harness, data, call};
}

test('deployment secret required; unauthenticated requests denied', async () => {
  const h = environment();
  assert.equal((await h.fetch(new Request('https://test/rooms', {method: 'POST'}))).status, 401);
  h.env.SERVICE_TOKEN = '';
  assert.equal((await h.fetch(request('/rooms', {method: 'POST'}))).status, 503);
});
test('room creation, authenticated join and wrong-room key rejection', async () => {
  const h = await room();
  assert.match(h.data.key, /^[a-f0-9]{64}$/);
  assert.equal((await h.call('join', {method: 'POST'})).status, 200);
  assert.equal((await h.call('join', {method: 'POST', headers: {'X-Room-Key': 'bad'}})).status, 403);
  assert.equal((await h.fetch(request(`/rooms/${'f'.repeat(32)}/join`, {method: 'POST'}))).status, 404);
});
test('chat round trip, cursor, and room isolation', async () => {
  const h = await room();
  const other = await room();
  assert.equal((await h.call('events', {method: 'POST', body: JSON.stringify({name: '민지', text: '안녕하세요 👍'})})).status, 200);
  const events = (await (await h.call('events')).json()).events;
  assert.equal(events[0].text, '안녕하세요 👍');
  assert.equal((await (await h.call(`events?after=${events[0].id}`)).json()).events.length, 0);
  assert.equal((await (await other.call('events')).json()).events.length, 0);
  assert.equal((await h.call('events?after=NaN')).status, 400);
});
test('invalid and oversized messages rejected; event retention bounded', async () => {
  const h = await room();
  for (const data of [{name: 'a', text: ''}, {name: 'a', text: 'x'.repeat(4001)}, {name: '', text: 'x'}]) {
    assert.equal((await h.call('events', {method: 'POST', body: JSON.stringify(data)})).status, 400);
  }
  assert.equal((await h.call('events', {method: 'POST', body: 'x'.repeat(16385)})).status, 400);
  for (let i = 0; i < 505; i++) h.rooms.get(h.data.id).event({type: 'chat', text: String(i), name: 'a'});
  const rows = h.rooms.get(h.data.id).sql.exec('SELECT * FROM events').toArray();
  assert.equal(rows.length, 500);
});
test('file upload/download, duplicate prevention and safe headers', async () => {
  const h = await room();
  const id = crypto.randomUUID(), bytes = new Uint8Array([0, 1, 255, 2]);
  const options = {method: 'PUT', body: bytes, headers: {'Content-Length': '4', 'X-File-Name': encodeURIComponent('한글.zip')}};
  assert.equal((await h.call(`files/${id}`, options)).status, 200);
  assert.equal((await h.call(`files/${id}`, options)).status, 409);
  const response = await h.call(`files/${id}`);
  assert.deepEqual(new Uint8Array(await response.arrayBuffer()), bytes);
  assert.match(response.headers.get('Content-Disposition'), /attachment/);
  assert.equal((await (await h.call('events')).json()).events[0].name, '한글.zip');
});
test('file size, filename and room file quota validation', async () => {
  const h = await room();
  const put = (size, name) => h.call(`files/${crypto.randomUUID()}`, {method: 'PUT', body: 'a', headers: {'Content-Length': String(size), 'X-File-Name': encodeURIComponent(name)}});
  assert.equal((await put(26 * 1024 * 1024, 'a')).status, 413);
  assert.equal((await put(0, 'a')).status, 413);
  assert.equal((await put(1, '../a')).status, 400);
  for (let i = 0; i < 100; i++) h.rooms.get(h.data.id).sql.exec('INSERT INTO files(id, name, size) VALUES (?, ?, ?)', String(i), 'a', 1);
  assert.equal((await put(1, 'a')).status, 429);
});
test('storage failure removes reservation and does not publish a file event', async () => {
  const h = await room();
  h.rooms.get(h.data.id).storeFile = async () => {throw new Error('storage unavailable');};
  assert.equal((await h.call(`files/${crypto.randomUUID()}`, {method: 'PUT', body: 'a', headers: {'Content-Length': '1', 'X-File-Name': 'a'}})).status, 502);
  assert.equal(h.rooms.get(h.data.id).sql.exec('SELECT * FROM files').toArray().length, 0);
  assert.equal((await (await h.call('events')).json()).events.length, 0);
});
test('expiration blocks access and alarm deletes files and room records', async () => {
  const h = await room();
  await h.call(`files/${crypto.randomUUID()}`, {method: 'PUT', body: 'a', headers: {'Content-Length': '1', 'X-File-Name': 'a'}});
  const instance = h.rooms.get(h.data.id);
  instance.sql.exec("UPDATE meta SET value = '0' WHERE key = 'expires'");
  assert.equal((await h.call('events')).status, 404);
  await instance.alarm();
  assert.equal(instance.sql.exec('SELECT * FROM chunks').toArray().length, 0);
  assert.equal(instance.meta('id'), undefined);
});
test('multi-chunk binary file roundtrip and chunk size bound', async () => {
  const h = await room();
  const id = crypto.randomUUID();
  const bytes = new Uint8Array(900001);
  for (let i = 0; i < bytes.length; i++) bytes[i] = i % 251;
  assert.equal((await h.call(`files/${id}`, {method: 'PUT', body: bytes, headers: {'Content-Length': String(bytes.length), 'X-File-Name': 'binary.bin'}})).status, 200);
  const chunks = h.rooms.get(h.data.id).sql.exec('SELECT length(bytes) AS n FROM chunks').toArray();
  assert.equal(chunks.length, 4);
  assert.ok(chunks.every(row => row.n <= 256 * 1024));
  assert.deepEqual(new Uint8Array(await (await h.call(`files/${id}`)).arrayBuffer()), bytes);
});
test('100 MiB room budget rejects additional files before reading body', async () => {
  const h = await room();
  const instance = h.rooms.get(h.data.id);
  for (let i = 0; i < 4; i++) instance.sql.exec('INSERT INTO files(id, name, size) VALUES (?, ?, ?)', String(i), 'existing.bin', 25 * 1024 * 1024);
  assert.equal((await h.call(`files/${crypto.randomUUID()}`, {method: 'PUT', body: 'a', headers: {'Content-Length': '1', 'X-File-Name': 'a'}})).status, 413);
  assert.equal(instance.sql.exec('SELECT * FROM files').toArray().length, 4);
});
test('truncated or oversized body removes all partial chunks', async () => {
  const h = await room();
  for (const declared of [300001, 299999]) {
    const response = await h.call(`files/${crypto.randomUUID()}`, {method: 'PUT', body: new Uint8Array(300000), headers: {'Content-Length': String(declared), 'X-File-Name': 'a'}});
    assert.equal(response.status, 502);
    assert.equal(h.rooms.get(h.data.id).sql.exec('SELECT * FROM chunks').toArray().length, 0);
    assert.equal(h.rooms.get(h.data.id).sql.exec('SELECT * FROM files').toArray().length, 0);
  }
});
test('simultaneous uploads are rejected without another reservation', async () => {
  const h = await room();
  let release, started;
  const gate = new Promise(resolve => {release = resolve;});
  const ready = new Promise(resolve => {started = resolve;});
  h.rooms.get(h.data.id).storeFile = async () => {started(); await gate;};
  const options = {method: 'PUT', body: 'a', headers: {'Content-Length': '1', 'X-File-Name': 'a'}};
  const first = h.call(`files/${crypto.randomUUID()}`, options);
  await ready;
  assert.equal((await h.call(`files/${crypto.randomUUID()}`, options)).status, 429);
  release();
  assert.equal((await first).status, 200);
  assert.equal(h.rooms.get(h.data.id).sql.exec('SELECT * FROM files').toArray().length, 1);
});
