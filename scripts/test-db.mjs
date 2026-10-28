import { PGlite } from '@electric-sql/pglite';
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const db = new PGlite();
try {
 await db.exec('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;');
 await db.exec(await readFile(new URL('../supabase/migrations/001_initial.sql',import.meta.url),'utf8'));
 const sample = (fingerprint,published)=>db.query(`INSERT INTO hackathons (fingerprint,title,start_date,official_source_url,verified,published,last_verified_at) VALUES ($1,$2,'2027-01-01','https://university.example.org/event',$3,$3,now()) RETURNING id`,[fingerprint,'Fixture test — never published externally',published]);
 const publicId=(await sample('published-fixture',true)).rows[0].id;
 await sample('private-fixture',false);
 await db.exec('SET ROLE anon');
 assert.equal((await db.query('SELECT * FROM public_hackathons')).rows.length,1,'RLS must hide unpublished records');
 await assert.rejects(db.query('SELECT evidence FROM hackathons'),'Private evidence must be inaccessible');
 await assert.rejects(db.query('SELECT * FROM sources'),'Source configuration is private');
 await assert.rejects(db.query("INSERT INTO hackathons(fingerprint,title,official_source_url) VALUES ('evil','evil','https://example.org')"),'Anonymous writes blocked');
 await db.exec('RESET ROLE');
 await assert.rejects(db.query("UPDATE hackathons SET registration_status='open' WHERE id=$1",[publicId]),'Open registration requires explicit evidence and registration URL');
 await assert.rejects(db.query("UPDATE hackathons SET end_date='2026-01-01' WHERE id=$1",[publicId]),'Invalid date ranges blocked');
 await assert.rejects(sample('published-fixture',true),'Fingerprint uniqueness blocks duplicates');
 await db.query("UPDATE hackathons SET start_date='2020-01-01' WHERE id=$1",[publicId]);
 await db.exec('SELECT archive_expired()');
 assert.equal((await db.query('SELECT archived FROM hackathons WHERE id=$1',[publicId])).rows[0].archived,true);
 await db.exec('SET ROLE anon');
 assert.equal((await db.query('SELECT registration_status FROM public_hackathons')).rows[0].registration_status,'closed');
 console.log('Database: migration, RLS, private fields, write protection, constraints, uniqueness and archival passed (embedded PostgreSQL).');
} finally { await db.close(); }
