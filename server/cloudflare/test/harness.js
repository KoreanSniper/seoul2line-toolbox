import {DatabaseSync} from 'node:sqlite';
import worker, {TransferRoom} from '../src/worker.js';

export function environment() {
  const rooms = new Map();
  const env = {
    SERVICE_TOKEN: 'test-service-token',
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
  return {env, rooms, fetch: request => worker.fetch(request, env)};
}

export function request(path, options = {}) {
  return new Request(`https://test${path}`, {...options, headers: {Authorization: 'Bearer test-service-token', ...options.headers}});
}
