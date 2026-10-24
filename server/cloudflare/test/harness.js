import {DatabaseSync} from 'node:sqlite';
import worker, {TransferRoom} from '../src/worker.js';

export function environment() {
  const objects = new Map(), rooms = new Map();
  const env = {
    SERVICE_TOKEN: 'test-service-token',
    FILES: {
      async put(key, stream) {objects.set(key, new Uint8Array(await new Response(stream).arrayBuffer()));},
      async get(key) {const bytes = objects.get(key); return bytes && {body: bytes, size: bytes.length};},
      async delete(keys) {for (const key of Array.isArray(keys) ? keys : [keys]) objects.delete(key);},
    },
    ROOMS: {
      idFromName: name => name,
      get(id) {
        if (!rooms.has(id)) {
          const db = new DatabaseSync(':memory:');
          const storage = {
            sql: {exec(query, ...args) {
              const statement = db.prepare(query);
              const rows = statement.columns().length ? statement.all(...args) : (statement.run(...args), []);
              return {toArray: () => rows};
            }},
            async setAlarm(time) {storage.alarm = time;},
            async deleteAll() {db.exec('DELETE FROM meta; DELETE FROM events; DELETE FROM files;');},
          };
          rooms.set(id, new TransferRoom({storage}, env));
        }
        return rooms.get(id);
      },
    },
  };
  return {env, rooms, objects, fetch: request => worker.fetch(request, env)};
}

export function request(path, options = {}) {
  return new Request(`https://test${path}`, {...options, headers: {Authorization: 'Bearer test-service-token', ...options.headers}});
}
