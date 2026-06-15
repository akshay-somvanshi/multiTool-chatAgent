"""
Populates the BigQuery `decarbonisation_plans` table with corporate decarbonisation plans
and targets extracted from sustainability reports of leading companies.

Usage:
    python populate_decarbonisation_plans.py [--industries "Retail,Manufacturing"] [--dry-run]
    python populate_decarbonisation_plans.py --supplement-with-llm
"""

import argparse
import json
import os
import time
import uuid
from datetime import datetime, timezone

import dotenv
import requests
from google import genai
from google.cloud import bigquery
from google.genai.types import GenerateContentConfig

dotenv.load_dotenv("/home/ubuntu_akshay/multiTool-chatAgent/ChatAgent/chat_agent/.env")

PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "dash-beta-e61d0")
DATASET_ID = "dash_beta_database"
TABLE_ID = "decarbonisation_plans"
GEMINI_MODEL = "gemini-3.5-flash"
GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_SEARCH_CX = os.getenv("GOOGLE_CSE_ID")

PLAN_SCHEMA = [
    bigquery.SchemaField("plan_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("industry", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("action_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("action_description", "STRING"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("target_year", "STRING"),
    bigquery.SchemaField("source_report", "STRING"),
    bigquery.SchemaField("last_updated", "TIMESTAMP"),
]

CORPORATE_COMPANIES = {
    "Retail": ["H&M", "Tesco", "IKEA", "Walmart", "Marks & Spencer"],
    "Manufacturing": ["Siemens", "BMW", "Jaguar Land Rover", "Toyota", "Tesla"],
    "Construction": ["Skanska", "Balfour Beatty", "Mace Group", "Kier Group", "Turner Construction"],
    "Financial Services": ["HSBC", "Aviva", "Barclays", "JPMorgan Chase", "Goldman Sachs"],
    "Healthcare": ["GSK", "AstraZeneca", "Bupa", "Pfizer", "Johnson & Johnson"],
    "Technology": ["Google", "Microsoft", "Apple", "BT Group", "Vodafone"],
    "Food & Beverage": ["Unilever", "Nestlé", "PepsiCo", "Diageo", "Coca-Cola"],
    "Logistics & Transport": ["DHL", "Royal Mail", "Maersk", "FedEx", "UPS"],
    "Energy & Utilities": ["National Grid", "BP", "Shell", "SSE", "NextEra Energy"],
    "Professional Services": ["Deloitte", "PwC", "Accenture", "EY", "KPMG"],
}

CURATED_PLANS = {
    "Retail": [
        {
            "company_name": "H&M",
            "action_name": "100% Recycled or Sustainably Sourced Materials",
            "action_description": "Commit to sourcing 100% recycled or sustainably sourced materials across all product lines to reduce scope 3 raw material emissions.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "H&M Group Sustainability Disclosure 2023",
        },
        {
            "company_name": "Tesco",
            "action_name": "Transition to Natural Refrigerants",
            "action_description": "Replace traditional high-GWP HFC refrigerants with natural alternatives (CO2 / hydrocarbons) in all retail store refrigeration systems.",
            "category": "Scope 1",
            "target_year": "2035",
            "source_report": "Tesco PLC Factsheet 2023/24",
        },
        {
            "company_name": "IKEA",
            "action_name": "100% Renewable Heating and Cooling",
            "action_description": "Phase out fossil fuels for heating and cooling across all retail stores and distribution centers, transitioning to heat pumps and biomass boilers.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "IKEA Sustainability Report FY23",
        },
        {
            "company_name": "Marks & Spencer",
            "action_name": "Plan A — Net Zero Operations",
            "action_description": "Achieve net zero across all direct operations (stores, offices, distribution) by decarbonising energy, refrigerants, and logistics fleets under the Plan A framework.",
            "category": "Scope 1",
            "target_year": "2040",
            "source_report": "M&S Plan A ESG Update 2023",
        },
        {
            "company_name": "Marks & Spencer",
            "action_name": "Sustainable Cotton Sourcing via Better Cotton",
            "action_description": "Source 100% of cotton from verified sustainable schemes (Better Cotton Initiative, organic, or recycled) to eliminate deforestation and agrochemical emissions.",
            "category": "Scope 3",
            "target_year": "2025",
            "source_report": "M&S Plan A ESG Update 2023",
        },
        {
            "company_name": "Walmart",
            "action_name": "Project Gigaton — Supplier Scope 3 Reduction",
            "action_description": "Engage over 4,500 suppliers to collectively avoid one billion metric tonnes of greenhouse gas emissions across the value chain through the Project Gigaton platform.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Walmart ESG Report 2023",
        },
        {
            "company_name": "Next",
            "action_name": "100% Renewable Electricity in UK Operations",
            "action_description": "Switch all UK retail stores and warehouses to 100% certified renewable electricity through REGO-backed tariffs and on-site solar installation.",
            "category": "Scope 2",
            "target_year": "2030",
            "source_report": "Next PLC Sustainability Report 2023",
        },
        {
            "company_name": "Primark",
            "action_name": "Primark Cares — Circular Fashion Commitment",
            "action_description": "Design all products to be made from recycled or more sustainably sourced materials and introduce in-store repair and recycling take-back services.",
            "category": "Circular Economy",
            "target_year": "2030",
            "source_report": "Primark Cares Sustainability Strategy 2023",
        },
        {
            "company_name": "ASOS",
            "action_name": "Fashion with Integrity — Responsible Packaging Elimination",
            "action_description": "Eliminate single-use virgin plastic polybags and replace all delivery packaging with recycled or FSC-certified materials.",
            "category": "Waste",
            "target_year": "2025",
            "source_report": "ASOS Fashion with Integrity Report 2023",
        },
    ],
    "Manufacturing": [
        {
            "company_name": "Siemens",
            "action_name": "Energy Efficiency Program in Factories",
            "action_description": "Implement waste heat recovery and high-efficiency motor systems across all manufacturing sites to reduce electricity consumption by 20%.",
            "category": "Scope 2",
            "source_report": "Siemens Sustainability Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "BMW",
            "action_name": "Low-Carbon Steel Procurement",
            "action_description": "Partner with steel manufacturers using hydrogen-based direct reduction processes instead of coal-fired blast furnaces to reduce raw material embodied carbon.",
            "category": "Scope 3",
            "source_report": "BMW Group Sustainable Value Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Jaguar Land Rover",
            "action_name": "Zero Waste to Landfill in Operations",
            "action_description": "Implement closed-loop aluminum recycling where manufacturing scrap is returned directly to suppliers to be melted back into high-quality sheets.",
            "category": "Circular Economy",
            "source_report": "JLR ESG Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Toyota",
            "action_name": "Hydrogen Fuel Cell Forklift Fleet",
            "action_description": "Deploy hydrogen fuel cell powered forklifts and material handling equipment in manufacturing plants to eliminate diesel and LPG emissions from factory logistics.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Toyota Environmental Challenge 2050 Progress Report 2023",
        },
        {
            "company_name": "Rolls-Royce",
            "action_name": "Net Zero Small Modular Reactors (SMR) Programme",
            "action_description": "Develop and commercialise compact nuclear reactors as a low-carbon energy source for industrial decarbonisation and grid balancing.",
            "category": "Scope 3",
            "target_year": "2035",
            "source_report": "Rolls-Royce SMR Programme Report 2023",
        },
        {
            "company_name": "BAE Systems",
            "action_name": "Supplier Decarbonisation Programme",
            "action_description": "Require all Tier 1 suppliers to disclose scope 1 and 2 emissions and commit to science-based targets as a condition of contract renewal.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "BAE Systems Responsible Business Report 2023",
        },
        {
            "company_name": "Dyson",
            "action_name": "100% Renewable Energy in Manufacturing",
            "action_description": "Transition all Dyson manufacturing sites in Malaysia and Singapore to renewable energy through Power Purchase Agreements and on-site solar.",
            "category": "Scope 2",
            "target_year": "2025",
            "source_report": "Dyson Environmental Progress Report 2023",
        },
        {
            "company_name": "Siemens",
            "action_name": "Zero-Carbon Factory Certification (DEGREE Framework)",
            "action_description": "Certify all manufacturing plants as carbon-neutral under Siemens' DEGREE sustainability framework, requiring on-site renewable energy and carbon offsets for residual emissions.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Siemens Sustainability Report 2023",
        },
    ],
    "Construction": [
        {
            "company_name": "Skanska",
            "action_name": "Use of Low-Carbon Concrete",
            "action_description": "Specify and use cement-free or low-carbon concrete alternatives (using fly ash/GGBS replacements) for all structural foundations.",
            "category": "Scope 3",
            "source_report": "Skanska Annual and Sustainability Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Balfour Beatty",
            "action_name": "Fossil Fuel-Free Construction Sites",
            "action_description": "Mandate the use of Hydrogenated Vegetable Oil (HVO) and hybrid generator batteries instead of red diesel for all on-site machinery and plant equipment.",
            "category": "Scope 1",
            "source_report": "Balfour Beatty Build to Last Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Mace Group",
            "action_name": "Prefabricated Modular Construction",
            "action_description": "Use off-site manufacturing and modular assembly to reduce transportation emissions and site waste by up to 50%.",
            "category": "Scope 3",
            "source_report": "Mace Group Annual Report 2023",
            "target_year": "2026",
        },
        {
            "company_name": "Morgan Sindall",
            "action_name": "Whole-Life Carbon Assessments on All Projects",
            "action_description": "Conduct RICS-aligned whole-life carbon assessments at design stage on all major projects to minimise embodied and operational carbon before breaking ground.",
            "category": "Scope 3",
            "target_year": "2025",
            "source_report": "Morgan Sindall Sustainability Report 2023",
        },
        {
            "company_name": "Kier Group",
            "action_name": "Electric Plant and Machinery Transition",
            "action_description": "Pilot and scale battery-electric excavators, dumpers, and tower cranes across major civil engineering projects to eliminate diesel combustion from plant.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Kier Group Sustainability Report 2023",
        },
        {
            "company_name": "Lendlease",
            "action_name": "Absolute Zero Carbon in Construction by 2025",
            "action_description": "Eliminate all construction-phase carbon emissions by switching to electric plant, low-carbon materials, and renewable site power — with no offsetting allowance.",
            "category": "Scope 1",
            "target_year": "2025",
            "source_report": "Lendlease Mission Zero Progress Report 2023",
        },
        {
            "company_name": "Skanska",
            "action_name": "Circular Waste Strategy — Zero Waste to Landfill",
            "action_description": "Divert 100% of construction site waste from landfill through segregation, reuse, and specialist recycling contracts, tracking per-tonne rates on every project.",
            "category": "Waste",
            "target_year": "2025",
            "source_report": "Skanska Annual and Sustainability Report 2023",
        },
        {
            "company_name": "Turner Construction",
            "action_name": "LEED and BREEAM Green Building Mandate",
            "action_description": "Require all new commercial projects over 50,000 sq ft to target LEED Gold or BREEAM Excellent certification to drive low-energy building design.",
            "category": "Scope 3",
            "target_year": "2027",
            "source_report": "Turner Construction Sustainability Report 2023",
        },
    ],
    "Financial Services": [
        {
            "company_name": "HSBC",
            "action_name": "Phase-out Coal Financing",
            "action_description": "Commit to phasing out financing for thermal coal-fired power plants and thermal coal mining in EU and OECD markets by 2030, and globally by 2040.",
            "category": "Scope 3",
            "source_report": "HSBC Climate Transition Plan 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Aviva",
            "action_name": "Divestment from Carbon-Intensive Companies",
            "action_description": "Divest from fossil fuel companies that do not have validated Science Based Targets (SBTi) aligned with a 1.5C pathway.",
            "category": "Scope 3",
            "source_report": "Aviva Climate Transition Plan 2023",
            "target_year": "2025",
        },
        {
            "company_name": "Barclays",
            "action_name": "Green Bond Underwriting Expansion",
            "action_description": "Increase the underwriting and advisory services for green and sustainability-linked bonds to facilitate client transition projects.",
            "category": "Scope 3",
            "source_report": "Barclays ESG Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "JPMorgan Chase",
            "action_name": "$2.5 Trillion Sustainable Finance Commitment",
            "action_description": "Deploy $2.5 trillion in green and sustainable finance including renewable energy project finance, green bonds, and ESG advisory services by 2030.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "JPMorgan Chase ESG Report 2023",
        },
        {
            "company_name": "Lloyds Banking Group",
            "action_name": "Green Mortgage and Home Retrofit Finance",
            "action_description": "Launch preferential mortgage rates for energy-efficient homes (EPC A/B rating) and green home improvement loans to finance customer decarbonisation of the built environment.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Lloyds Banking Group Responsible Business Report 2023",
        },
        {
            "company_name": "Legal & General",
            "action_name": "Net Zero Asset Management Portfolio by 2050",
            "action_description": "Align all investment portfolios with net zero by engaging portfolio companies, co-filing shareholder resolutions, and divesting from laggards that miss interim carbon targets.",
            "category": "Scope 3",
            "target_year": "2050",
            "source_report": "Legal & General Climate Report 2023",
        },
        {
            "company_name": "Aviva",
            "action_name": "Net Zero Internal Operations",
            "action_description": "Achieve net zero carbon across all owned and leased office buildings, business travel, and company car fleet by sourcing renewable energy and electrifying the fleet.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Aviva Climate Transition Plan 2023",
        },
        {
            "company_name": "Standard Chartered",
            "action_name": "Halving Financed Emissions Intensity by 2030",
            "action_description": "Reduce the carbon intensity of loans to power, steel, cement, and aviation sectors in line with PCAF standards and IEA Net Zero pathways.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Standard Chartered Sustainability Report 2023",
        },
    ],
    "Healthcare": [
        {
            "company_name": "GSK",
            "action_name": "100% Transition to Low-Carbon Inhalers",
            "action_description": "R&D investment to transition metered-dose inhalers (MDIs) to a propellant with a 99% lower carbon footprint than traditional HFAs.",
            "category": "Scope 3",
            "source_report": "GSK ESG Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "AstraZeneca",
            "action_name": "Zero Carbon Operations (Ambition Zero Carbon)",
            "action_description": "Achieve zero carbon emissions from global operations by 2025 by transitioning to 100% renewable electricity and heat.",
            "category": "Scope 1",
            "source_report": "AstraZeneca Sustainability Report 2023",
            "target_year": "2025",
        },
        {
            "company_name": "Bupa",
            "action_name": "Sustainable Medicines Procurement",
            "action_description": "Partner with pharmaceutical suppliers to enforce low-carbon packaging and transport criteria in healthcare supply contracts.",
            "category": "Scope 3",
            "source_report": "Bupa Sustainability Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Pfizer",
            "action_name": "Science Based Net Zero Target Across Value Chain",
            "action_description": "Reduce absolute scope 1, 2, and 3 emissions 95% by 2040 versus 2019 baseline across the full pharmaceutical supply chain, clinical operations, and patient distribution.",
            "category": "Scope 3",
            "target_year": "2040",
            "source_report": "Pfizer ESG Report 2023",
        },
        {
            "company_name": "Johnson & Johnson",
            "action_name": "100% Renewable Energy in Global Operations",
            "action_description": "Source 100% of global electricity from renewable sources across manufacturing plants, R&D facilities, and offices through a combination of PPAs, RECs, and on-site generation.",
            "category": "Scope 2",
            "target_year": "2025",
            "source_report": "Johnson & Johnson ESG Performance Summary 2023",
        },
        {
            "company_name": "Reckitt",
            "action_name": "Carbon-Neutral Manufacturing Sites",
            "action_description": "Achieve carbon neutrality across all Reckitt manufacturing sites by switching to renewable electricity, improving process energy efficiency, and using certified carbon offsets for residuals.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Reckitt ESG Sustainability Insights 2023",
        },
        {
            "company_name": "Haleon",
            "action_name": "Sustainable Packaging — 100% Recyclable or Reusable",
            "action_description": "Redesign all consumer healthcare product packaging to be 100% recyclable, reusable, or compostable, eliminating multi-material laminate and PVC blisters.",
            "category": "Scope 3",
            "target_year": "2025",
            "source_report": "Haleon ESG Report 2023",
        },
        {
            "company_name": "AstraZeneca",
            "action_name": "Low-Carbon Clinical Trials Logistics",
            "action_description": "Transition clinical trial supply chain to temperature-controlled electric courier vehicles and shift investigational product distribution to rail where feasible to reduce transport emissions.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "AstraZeneca Sustainability Report 2023",
        },
    ],
    "Technology": [
        {
            "company_name": "Google",
            "action_name": "24/7 Carbon-Free Energy Matching",
            "action_description": "Match electricity consumption hour-by-hour with local carbon-free energy sources on all grids where data centers operate.",
            "category": "Scope 2",
            "source_report": "Google Environmental Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Microsoft",
            "action_name": "Carbon Negative Operations and Historical Removal",
            "action_description": "Achieve net-negative emissions by purchasing high-permanence carbon removals to offset current and historical emissions.",
            "category": "Scope 1",
            "source_report": "Microsoft Environmental Sustainability Report FY23",
            "target_year": "2030",
        },
        {
            "company_name": "BT Group",
            "action_name": "Transition to 100% Electric Vehicle Fleet",
            "action_description": "Transition all telecom engineering and maintenance vehicles to electric models.",
            "category": "Scope 1",
            "source_report": "BT Group Manifesto Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Apple",
            "action_name": "Supplier Clean Energy Programme",
            "action_description": "Require all manufacturing suppliers to power Apple production with 100% clean electricity, verified annually, covering over 9 million tonnes of CO2 globally.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Apple Environmental Progress Report 2023",
        },
        {
            "company_name": "Vodafone",
            "action_name": "100% Renewable Electricity for Network Operations",
            "action_description": "Power all mobile network towers and base stations across Europe with renewable electricity via PPAs and green energy tariffs, eliminating the largest single source of Vodafone's emissions.",
            "category": "Scope 2",
            "target_year": "2025",
            "source_report": "Vodafone ESG Addendum 2023",
        },
        {
            "company_name": "Salesforce",
            "action_name": "Net Zero Cloud — Carbon Accounting for Customers",
            "action_description": "Offer enterprise customers a dedicated carbon accounting and sustainability reporting platform (Net Zero Cloud) to help measure and reduce value-chain emissions.",
            "category": "Scope 3",
            "target_year": "2026",
            "source_report": "Salesforce Stakeholder Impact Report FY23",
        },
        {
            "company_name": "Microsoft",
            "action_name": "Sustainable Data Centre Design — Water Positive",
            "action_description": "Design all new data centres to be water-positive by 2030 — replenishing more water than consumed in cooling — and eliminating single-use diesel backup generators.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Microsoft Environmental Sustainability Report FY23",
        },
        {
            "company_name": "BT Group",
            "action_name": "Energy Efficiency in Network — 'Switch off the Copper'",
            "action_description": "Decommission the legacy copper PSTN network in favour of energy-efficient full-fibre broadband, reducing the energy footprint of the national communications network by 80%.",
            "category": "Scope 2",
            "target_year": "2027",
            "source_report": "BT Group Manifesto Report 2023",
        },
    ],
    "Food & Beverage": [
        {
            "company_name": "Unilever",
            "action_name": "Regenerative Agriculture Practices",
            "action_description": "Implement regenerative agriculture codes for key ingredients (palm oil, soy, tea) to restore soil health and capture carbon.",
            "category": "Scope 3",
            "source_report": "Unilever Climate Transition Action Plan 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Nestlé",
            "action_name": "100% Deforestation-Free Primary Supply Chains",
            "action_description": "Use satellite monitoring and field audits to ensure cocoa, coffee, and palm oil supply chains do not contribute to deforestation.",
            "category": "Scope 3",
            "source_report": "Nestlé Creating Shared Value Report 2023",
            "target_year": "2025",
        },
        {
            "company_name": "Diageo",
            "action_name": "Water Stewardship in Water-Stressed Basins",
            "action_description": "Reduce water usage in breweries and distilleries by 30% and replenish water in water-stressed basins where ingredients are sourced.",
            "category": "Water/Resource",
            "source_report": "Diageo Society 2030 Report",
            "target_year": "2030",
        },
        {
            "company_name": "PepsiCo",
            "action_name": "pep+ Regenerative Farming Across 7 Million Acres",
            "action_description": "Spread regenerative agriculture practices across 7 million acres of cropland globally to remove carbon from the atmosphere and protect soil biodiversity in the food supply chain.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "PepsiCo PEP+ Progress Report 2023",
        },
        {
            "company_name": "Coca-Cola",
            "action_name": "100% Recyclable or Reusable Packaging",
            "action_description": "Transition all primary beverage packaging globally to 100% recyclable, reusable, or compostable formats and increase recycled content in plastic bottles to 50%.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Coca-Cola Business & Sustainability Report 2023",
        },
        {
            "company_name": "AB InBev",
            "action_name": "100% Renewable Electricity Across Breweries",
            "action_description": "Power all global brewing operations with 100% renewable electricity through on-site solar, wind PPAs, and green energy certificates.",
            "category": "Scope 2",
            "target_year": "2025",
            "source_report": "AB InBev ESG Report 2023",
        },
        {
            "company_name": "Greggs",
            "action_name": "Fleet Electrification and Depot Solar",
            "action_description": "Electrify the Greggs delivery vehicle fleet serving bakeries and install rooftop solar at distribution depots to eliminate diesel from owned logistics operations.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Greggs ESG Report 2023",
        },
        {
            "company_name": "Associated British Foods",
            "action_name": "Net Zero Sugar Cane Supply Chain",
            "action_description": "Work with sugar cane growers in partnership with Bonsucro to eliminate field burning, adopt precision irrigation, and measure farm-level GHG emissions across the sourcing base.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Associated British Foods Responsibility Report 2023",
        },
    ],
    "Logistics & Transport": [
        {
            "company_name": "DHL",
            "action_name": "80% Sustainable Aviation Fuel (SAF) Blend",
            "action_description": "Increase the share of Sustainable Aviation Fuel blends in air cargo operations to 80% to reduce shipping scope 3 emissions.",
            "category": "Scope 3",
            "source_report": "DHL Sustainability Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Royal Mail",
            "action_name": "Deploy 10,000 Electric Delivery Vans",
            "action_description": "Transition postal delivery fleet to electric vehicles, focusing on last-mile deliveries in urban clean air zones.",
            "category": "Scope 1",
            "source_report": "Royal Mail ESG Report 2023/24",
            "target_year": "2030",
        },
        {
            "company_name": "Maersk",
            "action_name": "Launch Net-Zero Ocean Vessels",
            "action_description": "Introduce ocean container vessels operating on green methanol and bio-fuels instead of heavy fuel oil.",
            "category": "Scope 1",
            "source_report": "Maersk Sustainability Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "UPS",
            "action_name": "Alternative Fuel and Advanced Technology Vehicle Fleet",
            "action_description": "Operate 40% of all ground delivery vehicles on alternative fuels (CNG, electric, hydrogen) and purchase 100% of aviation fuel as sustainable aviation fuel (SAF) by volume.",
            "category": "Scope 1",
            "target_year": "2025",
            "source_report": "UPS ESG Progress Report 2023",
        },
        {
            "company_name": "FedEx",
            "action_name": "Carbon-Neutral Global Operations",
            "action_description": "Achieve carbon-neutral operations through a $2bn investment in electric vehicle replacement, sustainable fuels for aircraft, and renewable energy at FedEx hubs and facilities.",
            "category": "Scope 1",
            "target_year": "2040",
            "source_report": "FedEx ESG Report FY23",
        },
        {
            "company_name": "DPD Group",
            "action_name": "Zero-Emission Urban Delivery Network",
            "action_description": "Electrify all last-mile delivery vehicles serving major European cities, establishing electric-only delivery zones in urban centres and installing depot fast-charging infrastructure.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "DPD Group Sustainability Report 2023",
        },
        {
            "company_name": "Wincanton",
            "action_name": "HVO Fuel Transition for Heavy Goods Fleet",
            "action_description": "Switch the entire HGV fleet to Hydrotreated Vegetable Oil (HVO) as an immediate drop-in fuel, delivering an 80–90% carbon reduction per kilometre with no infrastructure change.",
            "category": "Scope 1",
            "target_year": "2026",
            "source_report": "Wincanton Sustainability Report 2023",
        },
        {
            "company_name": "Maersk",
            "action_name": "Shore Power Connection at Major Ports",
            "action_description": "Connect all vessels to cold-ironing shore power at ports where infrastructure exists, eliminating auxiliary engine emissions during port calls.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Maersk Sustainability Report 2023",
        },
    ],
    "Energy & Utilities": [
        {
            "company_name": "National Grid",
            "action_name": "Grid Modernization for Renewable Integration",
            "action_description": "Upgrade transmission infrastructure to support the connection of offshore wind and solar generators to the UK national grid.",
            "category": "Scope 3",
            "source_report": "National Grid Climate Transition Plan 2023",
            "target_year": "2030",
        },
        {
            "company_name": "BP",
            "action_name": "Scale Up Electric Vehicle Charging Infrastructure",
            "action_description": "Deploy 100,000 public fast charging points globally to support the electrification of transport.",
            "category": "Scope 3",
            "source_report": "BP Net Zero Progress Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "SSE",
            "action_name": "Phase-out Coal-Fired Generation",
            "action_description": "Complete the decommissioning of remaining coal-fired power stations and invest £18B in renewable energy generation (wind/hydro).",
            "category": "Scope 1",
            "source_report": "SSE Net Zero Transition Plan 2023",
            "target_year": "2025",
        },
        {
            "company_name": "Centrica",
            "action_name": "Hydrogen Boiler Trials and Home Heat Decarbonisation",
            "action_description": "Run hydrogen boiler pilot programmes in UK residential properties and develop business model for hydrogen-ready retrofit kits as an alternative to heat pump installation.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Centrica Sustainability Report 2023",
        },
        {
            "company_name": "Drax",
            "action_name": "Bioenergy with Carbon Capture and Storage (BECCS)",
            "action_description": "Install carbon capture and permanent geological storage on biomass power generation units at Drax Power Station to generate negative emissions electricity at commercial scale.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Drax Sustainable Biomass Report 2023",
        },
        {
            "company_name": "Shell UK",
            "action_name": "Net Carbon Footprint of Energy Products",
            "action_description": "Reduce the net carbon intensity of all energy products sold (oil, gas, electricity, hydrogen) by 30% through low-carbon product substitution and customer-side carbon offsets.",
            "category": "Scope 3",
            "target_year": "2035",
            "source_report": "Shell Energy Transition Progress Report 2023",
        },
        {
            "company_name": "National Grid",
            "action_name": "Supply Chain Sustainability — Net Zero Procurement",
            "action_description": "Require all National Grid contractors and major material suppliers to disclose emissions and commit to science-based targets as a procurement condition.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "National Grid Climate Transition Plan 2023",
        },
        {
            "company_name": "SSE",
            "action_name": "Offshore Wind Capacity — 8GW by 2030",
            "action_description": "Invest £18B to build and operate 8 gigawatts of offshore wind capacity, making SSE one of Europe's largest renewables developers and displacing fossil fuel generation.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "SSE Net Zero Transition Plan 2023",
        },
    ],
    "Professional Services": [
        {
            "company_name": "Deloitte",
            "action_name": "Sustainable Travel Policy",
            "action_description": "Mandate a 50% reduction in business travel emissions per employee compared to 2019 levels by promoting virtual-first client meetings and rail over air travel.",
            "category": "Scope 3",
            "source_report": "Deloitte Global Impact Report 2023",
            "target_year": "2030",
        },
        {
            "company_name": "PwC",
            "action_name": "100% Virtual Office Consolidation",
            "action_description": "Consolidate physical office locations and optimize HVAC/lighting energy efficiency in shared professional hubs.",
            "category": "Scope 2",
            "source_report": "PwC Global Annual Review 2023",
            "target_year": "2030",
        },
        {
            "company_name": "Accenture",
            "action_name": "100% Renewable Electricity in Global Offices",
            "action_description": "Purchase renewable energy credits (RECs) and match office utility contracts with green tariffs across all leased buildings.",
            "category": "Scope 2",
            "source_report": "Accenture 360 Value Report 2023",
            "target_year": "2025",
        },
        {
            "company_name": "EY",
            "action_name": "Carbon Negative Business Travel Programme",
            "action_description": "Invest in high-quality carbon removal credits and introduce an internal carbon price on all business flights to drive modal shift and fund permanent removal projects.",
            "category": "Scope 3",
            "target_year": "2025",
            "source_report": "EY Value Realized ESG Report 2023",
        },
        {
            "company_name": "KPMG",
            "action_name": "Net Zero Supply Chain — Supplier Engagement Programme",
            "action_description": "Engage all significant KPMG suppliers to disclose scope 1 and 2 emissions data and set emission reduction targets, incorporating climate performance into supplier scorecards.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "KPMG Impact Plan 2023",
        },
        {
            "company_name": "Capgemini",
            "action_name": "Net Zero Operations — Absolute Emissions Reduction",
            "action_description": "Reduce absolute scope 1 and 2 emissions 90% by 2030 versus 2019 by decarbonising office buildings, data centres, and employee commuting without relying on carbon credits for these scopes.",
            "category": "Scope 1",
            "target_year": "2030",
            "source_report": "Capgemini Sustainability Report 2023",
        },
        {
            "company_name": "Deloitte",
            "action_name": "Green Lease Office Portfolio",
            "action_description": "Negotiate green lease clauses with all landlords requiring landlords to share energy data, target EPC A/B ratings, and use 100% renewable electricity for shared building services.",
            "category": "Scope 2",
            "target_year": "2025",
            "source_report": "Deloitte Global Impact Report 2023",
        },
        {
            "company_name": "Accenture",
            "action_name": "360° Value Client Decarbonisation Practice",
            "action_description": "Build and deploy dedicated decarbonisation advisory teams helping clients set and track science-based targets, measure full value-chain emissions, and implement transition roadmaps.",
            "category": "Scope 3",
            "target_year": "2030",
            "source_report": "Accenture 360 Value Report 2023",
        },
    ],
}

DEFAULT_INDUSTRIES = list(CURATED_PLANS.keys())


def ensure_table(bq_client: bigquery.Client) -> None:
    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    try:
        table = bq_client.get_table(table_ref)
        print(f"Table {table_ref} already exists.")
        existing_names = {f.name for f in table.schema}
        new_fields = [f for f in PLAN_SCHEMA if f.name not in existing_names]
        if new_fields:
            table.schema = list(table.schema) + new_fields
            bq_client.update_table(table, ["schema"])
            print(f"  Schema evolved: added {[f.name for f in new_fields]}")
    except Exception:
        table = bigquery.Table(table_ref, schema=PLAN_SCHEMA)
        bq_client.create_table(table)
        print(f"Created table {table_ref}.")


def get_existing_plan_keys(bq_client: bigquery.Client, industry: str) -> set[tuple]:
    """Returns a set of (lower_company_name, lower_action_name) tuples already in BQ."""
    query = f"""
        SELECT LOWER(company_name) as cname, LOWER(action_name) as aname
        FROM `{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}`
        WHERE LOWER(industry) = @industry
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("industry", "STRING", industry.lower())]
    )
    try:
        results = bq_client.query(query, job_config=job_config).result()
        return {(row.cname, row.aname) for row in results}
    except Exception:
        return set()


def insert_plans(
    bq_client: bigquery.Client,
    industry: str,
    plans: list[dict],
    dry_run: bool,
) -> int:
    existing = get_existing_plan_keys(bq_client, industry)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for p in plans:
        company = p.get("company_name", "").strip()
        action = p.get("action_name", "").strip()
        if not company or not action or (company.lower(), action.lower()) in existing:
            continue
        rows.append({
            "plan_id": str(uuid.uuid4()),
            "industry": industry,
            "company_name": company,
            "action_name": action,
            "action_description": p.get("action_description", ""),
            "category": p.get("category", ""),
            "target_year": str(p.get("target_year", "")),
            "source_report": p.get("source_report", ""),
            "last_updated": now,
        })

    if not rows:
        print(f"  No new decarbonisation plans to insert for {industry} (all already present).")
        return 0

    if dry_run:
        print(f"  [dry-run] Would insert {len(rows)} plans for {industry}:")
        for r in rows:
            print(f"    - [{r['company_name']}] {r['action_name']}  |  {r['source_report']}")
        return len(rows)

    table_ref = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"
    errors = bq_client.insert_rows_json(bq_client.get_table(table_ref), rows)
    if errors:
        print(f"  BigQuery insert errors for {industry}: {errors}")
        return 0

    print(f"  Inserted {len(rows)} new decarbonisation plans for {industry}.")
    return len(rows)


def google_search(query: str, num: int = 8) -> list[dict]:
    if not GOOGLE_SEARCH_API_KEY or not GOOGLE_SEARCH_CX:
        return []
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": GOOGLE_SEARCH_API_KEY, "cx": GOOGLE_SEARCH_CX, "q": query, "num": num},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        return [
            {"title": item.get("title", ""), "snippet": item.get("snippet", ""), "url": item.get("link", "")}
            for item in items
        ]
    except Exception as e:
        print(f"  [search] Query failed ({query!r}): {e}")
        return []


def search_plan_sources(industry: str) -> list[dict]:
    queries = [
        f"{industry} companies net zero transition plan decarbonisation targets initiatives",
        f"{industry} sustainability report carbon reduction actions",
    ]
    results = []
    for q in queries:
        results += google_search(q, num=5)
        time.sleep(0.5)
    return results


def supplement_with_llm(
    industry: str,
    existing_keys: set[tuple],
    search_results: list[dict],
    gemini_client: genai.Client,
) -> list[dict]:
    search_context = ""
    if search_results:
        snippets = "\n".join(
            f"- [{r['title']}] ({r['url']}): {r['snippet']}" for r in search_results[:10]
        )
        search_context = f"\nWeb search results for grounding:\n{snippets}\n"

    prompt = f"""You are an expert in corporate sustainability and climate change transition plans.

Your task: Suggest concrete decarbonisation initiatives and targets from actual sustainability reports of leading companies in the {industry} industry.
Only include real, currently active company commitments. Avoid vague actions.

{search_context}

Return 5-10 additional decarbonisation actions. For each provide:
- company_name: the real name of the company publishing the plan
- action_name: a concise name of the action/initiative (e.g. "Transition to 100% Electric delivery fleet")
- action_description: 1-2 sentences on what the requirement/action actually entails
- category: one of [Scope 1, Scope 2, Scope 3, Circular Economy, Waste, Resource]
- target_year: the year they target to complete this (e.g. "2030", "2045")
- source_report: the document/source title (e.g. "[Company] 2023 Sustainability Report")

Return ONLY valid JSON:
{{
  "plans": [
    {{
      "company_name": "...",
      "action_name": "...",
      "action_description": "...",
      "category": "...",
      "target_year": "...",
      "source_report": "..."
    }}
  ]
}}"""

    for attempt in range(3):
        try:
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(response.text).get("plans", [])
        except Exception as e:
            print(f"  [llm] Attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                return []
            time.sleep(2 ** attempt)
    return []


def populate_industry(
    industry: str,
    bq_client: bigquery.Client,
    gemini_client: genai.Client | None,
    dry_run: bool,
    use_llm_supplement: bool,
) -> int:
    print(f"\nProcessing Industry: {industry}")

    curated = CURATED_PLANS.get(industry, [])
    print(f"  {len(curated)} curated decarbonisation plans")

    inserted = insert_plans(bq_client, industry, curated, dry_run)

    if use_llm_supplement and gemini_client is not None:
        existing_keys = get_existing_plan_keys(bq_client, industry)
        search_results = search_plan_sources(industry)
        print(f"  Running LLM supplementation ({len(search_results)} search results found)...")
        extra = supplement_with_llm(industry, existing_keys, search_results, gemini_client)
        print(f"  LLM suggested {len(extra)} additional decarbonisation plans.")
        inserted += insert_plans(bq_client, industry, extra, dry_run)

    return inserted


def main():
    parser = argparse.ArgumentParser(description="Populate decarbonisation_plans BigQuery table.")
    parser.add_argument(
        "--industries",
        type=str,
        default=None,
        help="Comma-separated list of industries (default: all curated industries)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing to BigQuery",
    )
    parser.add_argument(
        "--supplement-with-llm",
        action="store_true",
        help="After inserting curated plans, run a Gemini pass to search and suggest extra corporate initiatives",
    )
    args = parser.parse_args()

    industries = (
        [i.strip() for i in args.industries.split(",")]
        if args.industries
        else DEFAULT_INDUSTRIES
    )

    bq_client = bigquery.Client(project=PROJECT_ID)
    gemini_client = None
    if args.supplement_with_llm:
        gemini_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

    if not args.dry_run:
        ensure_table(bq_client)

    total_inserted = 0
    for industry in industries:
        total_inserted += populate_industry(
            industry,
            bq_client,
            gemini_client,
            dry_run=args.dry_run,
            use_llm_supplement=args.supplement_with_llm,
        )

    print(f"\nDone. Total decarbonisation plans inserted: {total_inserted}")


if __name__ == "__main__":
    main()
