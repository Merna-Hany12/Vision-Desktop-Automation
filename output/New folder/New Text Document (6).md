* Menu

Menu source: PDF upload / manual text

Menu sections: appetizers, mains, desserts, drinks, specials

Item fields: name, description, price, photo URL, category, availability flag



* Ordering

Order channels: dine-in, takeaway, delivery

Minimum order amount for delivery

Estimated prep time per order type (dine-in / takeaway / delivery)

Customization rules (e.g. "can remove onions, cannot substitute protein")

Combo / upsell suggestions — agent prompts these when order is placed



* Delivery

Zones served + delivery fee per zone

Estimated delivery time per zone



* Orders data (F\&B-specific additions)

Order types column: dine-in / takeaway / delivery

Table number field (for dine-in)

Rider name / tracking info field (for delivery)

Special instructions field per order

Estimated ready time field



* Tickets \& complaints (F\&B-specific additions)

Additional complaint categories: wrong item delivered, cold food, missing item, food quality, long wait

Food quality complaint rule: always apologise + offer replacement or refund, then log ticket

Compensation policy: replacement / discount code / refund (configurable per complaint type)









retail store



Store identity

\- Store type: fashion / electronics / kids \& toys / bookstore

\- Store model: physical only / online only / omnichannel (both)

\- Number of branches

\- Brand positioning: budget / mid-range / premium / luxury — affects agent tone when discussing price



\*\*Product catalog (additions to generic catalog section)\*\*

\- Catalog sheet fields: product ID, name, category, subcategory, brand, description, price, discounted price, SKU, barcode, color, size, material, weight, dimensions, photo URL, availability flag, stock quantity, branch availability (which branches carry this item), new arrival flag, best seller flag, featured flag

\- Variant handling: one parent product with multiple variants (size S/M/L/XL, color red/black/white) — each variant has its own SKU and stock count

\- Bundle / set products: list of included items + bundle price vs individual total

\- Product tags for filtering: waterproof, handmade, local brand, imported, sale, limited edition

\- Agent rule: always confirm which specific variant (size + color) is available before confirming stock

\- Agent rule: if product has multiple variants, ask customer to specify before checking availability



\*\*Inventory \& stock\*\*

\- Stock source: Google Sheet / ERP system (e.g. Odoo, SAP) / POS sync (e.g. Vend, Lightspeed)

\- Stock sync frequency: real-time / hourly / daily

\- Stock quantity thresholds: in stock / low stock (below X units) / out of stock

\- Low stock behavior: inform customer + offer to reserve / add to waitlist / suggest alternative

\- Out-of-stock behavior: suggest similar items / collect restock notification request / offer to check other branches

\- Branch stock check: if item is out of stock at one branch, agent checks other branches automatically

\- Reserved stock: items reserved for X hours after customer expresses intent to buy

\- Restock date field: if known, agent shares estimated restock date with customer

\- Damaged / defective stock flag: agent never confirms damaged items as available



\*\*Pricing \& promotions\*\*

\- Price types: regular price, sale price, member price, wholesale price (agent uses the right one per customer type)

\- Active promotions sheet: promo name, discount type (percentage / fixed amount / buy X get Y / free shipping), applicable products or categories, start date, end date, promo code (if any), stackable with other promos (yes/no)

\- Flash sale flag: time-limited offer with countdown — agent mentions urgency when relevant

\- Loyalty program: points per purchase, redemption rate, current points balance lookup

\- Price match policy: does the store match competitor prices yes/no + conditions

\- Agent rule: always validate promo code before confirming discount to customer

\- Agent rule: never apply two non-stackable promos simultaneously

\- Agent rule: if sale ends today, mention it once — don't pressure repeatedly



\*\*Sizing \& fit guidance\*\*

\- Size guide per category: clothing (XS–XXL + measurements), shoes (EU/UK/US sizing), kids (age-based sizing)

\- Size guide sheet or URL: agent shares link when customer asks

\- Fit type field per product: slim fit / regular fit / oversized / relaxed

\- Agent rule: if customer is unsure of size, ask for measurements or direct to size guide — never guess

\- Agent rule: mention exchange policy proactively when a size-related purchase is confirmed



\*\*Browsing \& recommendations\*\*

\- Agent recommendation logic:

&#x20; - If customer is undecided: ask for occasion, budget, preference (color, style) then suggest from best sellers + new arrivals

&#x20; - If customer asks "what's new": pull items with new arrival flag from the last 30 days

&#x20; - If customer asks "what's on sale": pull items with active sale price

&#x20; - If customer views one item: suggest complementary items (outfit matching, accessories)

&#x20; - If item is out of stock: immediately suggest 2–3 alternatives from same category + price range

\- Wishlist / save for later: collect customer name + phone + product ID → log to wishlist sheet → notify when item restocks or goes on sale

\- Gift recommendations: if customer says "gift for someone" — ask recipient gender, age, budget, occasion → suggest from featured + best seller items



\*\*Orders (retail-specific additions)\*\*

\- Order types: in-store purchase / online order / click \& collect (buy online, pick up in store) / phone order

\- Click \& collect fields: branch selected, ready-by time, collection window (how many days to collect before order is released)

\- Gift wrapping option: yes/no + fee + message card text field

\- Order sheet additional fields: order type, branch ID (for in-store or collection), gift wrap flag, gift message, discount applied, loyalty points earned, loyalty points redeemed

\- Pre-order: for out-of-stock or upcoming items — collect deposit + expected arrival date

\- Bulk / corporate orders: flag for orders above X units — escalate to sales team for special pricing



\*\*Delivery \& shipping\*\*

\- Shipping zones: local (same city) / national / international — each with its own fee and estimated time

\- Courier partners: which courier per zone (e.g. Aramex for international, in-house for local)

\- Same-day delivery: available yes/no + cutoff time + additional fee + zones covered

\- Next-day delivery: available yes/no + cutoff time

\- Free shipping threshold: order amount above which shipping is free

\- Fragile item handling: extra packaging fee + courier restriction (not all couriers handle fragile)

\- Tracking: courier tracking link format — agent generates and shares when order is shipped

\- International shipping: customs / duties responsibility (customer or store) + restricted countries list



\*\*Returns \& exchanges (retail-specific detail)\*\*

\- Return window: X days from purchase or delivery date

\- Return conditions: unused, original packaging, tags attached, receipt required

\- Non-returnable items: underwear, swimwear, pierced jewelry, personalized items, sale items (if applicable)

\- Exchange policy: same item different size/color / different item up to same value / store credit

\- Refund method: original payment method / store credit / cash (in-store only)

\- Return initiation: customer contacts agent → agent collects order ID + reason + photo (if damaged) → logs to returns sheet → sends return instructions

\- Return shipping: customer pays / store pays / free if item is defective

\- Processing time: X business days for refund to appear after item is received

\- Agent rule: always check if item is within return window before accepting a return request

\- Agent rule: if item is defective, prioritize replacement over refund and waive return shipping



\*\*In-store experience\*\*

\- Branch details sheet: branch ID, address, area, phone, working hours, parking availability, fitting rooms (yes/no), alterations service (yes/no), gift wrapping station (yes/no)

\- In-store services: personal shopping assistance, alterations, engraving, gift wrapping, loyalty card issuance

\- Fitting room reservation: available yes/no — agent books a slot if available

\- Stylist / personal shopper booking: available yes/no + how to book

\- Agent rule: if customer asks about a specific branch — pull that branch's details from the branch sheet



\*\*Tickets \& complaints (retail-specific additions)\*\*

\- Additional complaint categories: wrong item received, missing item in order, damaged item, item not as described, counterfeit concern, staff behavior, long wait at branch, billing error

\- Wrong item / missing item flow: collect order ID + photo → log ticket → offer replacement or refund → escalate to fulfillment team

\- Counterfeit concern: treat as highest priority → escalate to store manager immediately → never dismiss

\- Agent rule: for any complaint involving a photo, ask customer to send it and note "photo received" in the ticket log



\*\*Retail-specific system prompt rules\*\*

\- Never confirm stock without checking the live availability flag — stock changes throughout the day

\- Never promise a delivery date not confirmed by the shipping system

\- Never apply a discount or promo not in the active promotions sheet

\- Always mention the return policy when confirming a purchase, especially for sale items

\- If customer asks to compare two products, list key differences clearly without dismissing either option

\- Never push a customer toward a more expensive item if their budget is clear — suggest within their range

\- Always confirm size, color, and variant before placing any order













Brand

\- Store name + agent name

\- Fashion type: women's / men's / kids / unisex

\- Style: casual / formal / modest / luxury



Catalog

\- Product ID, name, category

\- Price, discounted price

\- Color, size, material

\- Photo URL

\- Availability flag per variant

\- Best seller flag, new arrival flag



\*\*Policies\*\*

\- Working hours + branch locations

\- Payment methods

\- Return window + conditions

\- Non-returnable items

\- Delivery zones + fees



\*\*Tickets \& complaints\*\*

\- Ticket sheet URL

\- Complaint categories: wrong item, defect, color mismatch, size label error, damaged item



\*\*Customer data\*\*

\-Title: Fallback Mock Post 1



This is some mock content for post 1 because the network API request failed. The automation will type this out anyway!

