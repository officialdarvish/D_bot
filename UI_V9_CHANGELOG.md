# UI v9 Final Fixes

## Website & SSL
- When SSL is applied successfully from the Website & SSL card, the panel now requests a restart for both API/site and bot services.
- Added Docker socket mount in docker-compose so the API container can restart the Compose `api` and `bot` services without needing the Docker CLI inside the image.
- The Website & SSL card now exposes restart status and restart message.

## Users
- Users API pagination is now used by the React UI.
- The Users section shows Previous / Next pagination when there are more than 100 users.

## Test Account
- Added a website card/table for users who already used the test account.
- Added a Reset all test-account users action in the website panel.
- Inbound IDs are now shown as selectable chips from the selected server's synced inbounds.
- Admin can select individual inbounds, select all, or keep automatic all-inbound behavior.

## Servers
- Add Server modal has a Test Connection button.
- Server add/edit now tests the panel and synchronizes inbound IDs.
- Server Test & Update now tests panel connectivity, refreshes inbound IDs, and updates related plans/build configs.

## Plans
- Public plan edit now refreshes inbound IDs from the selected server when the server changes.
- Server-bound plans are kept synced when server inbounds are refreshed.

## Resellers
- Reseller page now shows reseller top-up/menu plans.
- Reseller plan editing uses the real server list.
