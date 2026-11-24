-- Only trusted backend code sets these transaction-local values after verification.
-- No browser/database connection is exposed; all other ownership policies remain in force.
CREATE POLICY "googleIdentityLookup" ON "oauthAccounts" FOR SELECT
 USING ("provider"='google' AND "issuer"='https://accounts.google.com'
 AND "subject"=nullif(current_setting('app.googleSubject',true),''));
CREATE POLICY "sessionTokenLookup" ON "sessions" FOR SELECT
 USING ("sessionTokenHash"=nullif(current_setting('app.sessionTokenHash',true),''));
