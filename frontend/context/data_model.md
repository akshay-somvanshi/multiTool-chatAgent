## Collections (2)
- users: email (String), uid (String), created_time (DateTime), first_name (String), last_name (String), display_name (String), phone_number (String), photo_url (ImagePath), company_name (String), company_industry (String), team (String), stripe_enabled (Boolean), sustainability_strategy (Boolean), operate_in_uk (Boolean), initial_info_1_complete (Boolean), initial_info_2_complete (Boolean), remainingAiSearches (Integer), hasInitialisedRemainingAiSearches (Boolean), subscriptionPlanId (Integer)
- messages: uid (String), role (String), message (String), timeStamp (DateTime), fileUrl (String), sessionID (String)
  - Used by: initial-information-2

## Enums (2)
- role: user, ai
- isFromPageNames: dashboard, knowledge

## Data Structs (6)
- ChatMessage: role (Enum<role>), message (String), isLoading (Boolean), timestamp (DateTime), fileUrl (String), uid (String), isDocuments (Boolean), fileURLs (List<DataStruct<?>>), actions (List<DataStruct<?>>)
- ExploreData: supplier_id (String), supplier_name (String), supplier_country (String), supplier_type (String)
- knowledgeScreenData: file_name (String), gcs_path (String), size_bytes (Integer), content_type (String), updated (String)
- UploadFileData: name (String), path (String)
- DashboardDataType: action_id (String), action_name (String), action_type (String), action_description (String), estimated_spend (Integer), estimated_co2_reduced (Integer), estimated_revenue_unlocked (Integer), plan_id (String), timeline_start (String), timeline_end (String), status (String)
- ShowActionsInChat: id (String), title (String), description (String), co2_reduction (Integer), spend (Integer), revenue (Integer), status (String)

