## Custom Code
### Functions
- getMessages(prevMessages: List<String>, prevFiles: List<String>, userInput: String) → String
- imageReturn(image: String) → ImagePath
- returnListOfStringFromImageURL(imageURLs: List<String>) → String
- formatDateToDDMonYY(dateString: String) → String
- stringToInt(stringValue: String) → Integer
- apiJsonValueToString(stringValue: String) → String
- sumPositiveAndNegativeIntegers(values: List<Integer>) → Integer
- returnFirstInProgressActionIndex(statuses: List<String>) → Integer
- fileSizeFromTheTheUploadedFile(file: UploadedFile) → String
- returnlastIndex(chatlist: List<DataStruct<?>>) → Integer
- removeQuotationsFromString(input: String) → String
### Actions
- getMessageLength(userMessage: String) → Integer
- downloadSingleDataOfDashboardInCsv(dashboardDataType: DataStruct<DashboardDataType>)
- downloadMultipleDataOfDashboardInCsv(dashboardDataType: List<DataStruct<?>>)
### Widgets
- ProgressBar(currentStep: Integer, totalSteps: Integer, selectedIndex: Action)
- DocumentCoverPreview(documentUrl: String, borderRadius: Double)
- HtmlViewer(maxHeight: Double, description: String, borderColor: Color, bgColor: Color)
- CustomLoadingIndicator(indicatorSize: Double)
- WorkingShimmerText(text: String, fontSize: Double)

