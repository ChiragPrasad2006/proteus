import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = path.resolve(import.meta.dirname, '..')
const src = path.join(root, 'src')
const files = []

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) walk(full)
    else if (/\.(ts|tsx)$/.test(entry.name)) files.push(full)
  }
}

walk(src)

const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8')
const failures = []

function expect(condition, message) {
  if (!condition) failures.push(message)
}

const store = read('src/stores/useAppStore.ts')
expect(!/SEED_(ACCOUNTS|SESSIONS|MESSAGES|DRAFT|CONTACTS)/.test(store), 'useAppStore still exports seed data')
expect(/accounts:\s*\[\]/.test(store), 'useAppStore accounts must initialize to []')
expect(/sessions:\s*\[\]/.test(store), 'useAppStore sessions must initialize to []')
expect(/messages:\s*\[\]/.test(store), 'useAppStore messages must initialize to []')

const api = read('src/lib/api.ts')
expect(/googleAuthStart/.test(api), 'api.ts must expose googleAuthStart')
expect(/switchAccount/.test(api), 'api.ts must expose switchAccount')
expect(/listContacts/.test(api), 'api.ts must expose listContacts')
expect(/X-Account-ID/.test(api), 'api.ts must send X-Account-ID')

const switcher = read('src/components/workspace/AccountSwitcher.tsx')
const storeState = read('src/stores/useAppStore.ts')
expect(/setActiveAccount/.test(switcher), 'AccountSwitcher must select the requested account')
expect(/switchAccount/.test(storeState), 'Account switching must update the backend account')
expect(/listSessions/.test(storeState), 'Account switching must reload sessions')
expect(/profile/.test(storeState), 'Account switching must reload the profile')
expect(/listContacts/.test(storeState), 'Account switching must reload contacts')
expect(!/alert\(/.test(switcher), 'AccountSwitcher must not use alert()')

const hero = read('src/components/landing/Hero.tsx')
expect(/startGoogleSignIn/.test(hero), 'Hero must use shared startGoogleSignIn flow')
expect(fs.existsSync(path.join(root, 'src/components/auth/ConnectGmailModal.tsx')), 'Connect Gmail modal is missing')

for (const file of files) {
  const relative = path.relative(root, file).replaceAll('\\', '/')
  const content = fs.readFileSync(file, 'utf8')
  expect(!/SEED_(ACCOUNTS|SESSIONS|MESSAGES|DRAFT|CONTACTS)/.test(content), `${relative} still references seed data`)
  expect(!/d\.reyes@acme-holdings\.com|priya\.nair@atlasdesign\.io|maya@northwind\.co/.test(content), `${relative} still contains mock contact/account data`)
}

if (failures.length) {
  console.error(failures.map((failure) => `FAIL: ${failure}`).join('\n'))
  process.exit(1)
}

console.log(`Frontend contract checks passed (${files.length} source files scanned).`)
