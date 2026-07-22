[GET]:https://ceir.gov.mm/openapi/API/Device/personal-device-info?altcha=eyJhbGdvcml0aG0iOiJTSEEtMjU2IiwiY2hhbGxlbmdlIjoiY2MxYjQ2NDFlODA2YzU0ZDQ5YjEyNmRiYzdiMmM1ZjFhY2EyNGFiMDVlZTE2NmNhYjBlZjA0MzhlMTVhNjgxZSIsIm51bWJlciI6NTQxODIwLCJzYWx0IjoiYTg0OTc3ZDM2NGJjMmQzM2Q2ZmNhOWUyP2V4cGlyZXM9MTc4NDcxODk2NiYiLCJzaWduYXR1cmUiOiIyNGZlYzJlYjZjZDc4Y2I3NGYwODdjNGExM2I2MDA4OWMyODE4NThlMjNiMTE2MDg2YTZmMTdkMGZjZDQwMzY5IiwidG9vayI6MzgxN30=&imei=350782287836844

response 
{
    "tac": "35399510",
    "shortIMEI": "4166297",
    "gsmaModelName": "iPhone 17 Pro Max A3526",
    "gsmaImeiQuantitySupport": 2,
    "gsmaDeviceType": "Smartphone",
    "gsmaManufacturer": "Apple",
    "gsmaBrandName": "Apple",
    "gsmaAllocationDate": "11-Mar-2026",
    "gsmaOperatingSystem": "iOS"
}

==============================


[GET]https://www.ceir.gov.mm/openapi/API/IMEI/RegistrationStatus?DeclarationID=MM-CR-51PX4FJ&altcha=eyJhbGdvcml0aG0iOiJTSEEtMjU2IiwiY2hhbGxlbmdlIjoiZmE0YzliOGQ4ODlhMDBjYzg3ODliN2E4MmFhMzg1ZWI1ZDI5Y2I1ZTE5Mjk0NDhjMzY4MGY2ZjJmM2QzOTdlZCIsIm51bWJlciI6NDIwMTE5LCJzYWx0IjoiYzVlYWM1NGNhYTQwMGEwNzI3ZTU4ZjBhP2V4cGlyZXM9MTc4NDcyMDUxOSYiLCJzaWduYXR1cmUiOiJhMDgxNGNlZTVkN2Q4ZWU4MDdiMjBmODY2YzU4NDQ5MDJmYTc0YTNlMzU1ZGU3NTgyZDFjYjBmYzg1OTU4OTFlIiwidG9vayI6MTIyOTZ9

payload{
    DeclarationID=MM-CR-51PX4FJ&altcha=eyJhbGdvcml0aG0iOiJTSEEtMjU2IiwiY2hhbGxlbmdlIjoiZmE0YzliOGQ4ODlhMDBjYzg3ODliN2E4MmFhMzg1ZWI1ZDI5Y2I1ZTE5Mjk0NDhjMzY4MGY2ZjJmM2QzOTdlZCIsIm51bWJlciI6NDIwMTE5LCJzYWx0IjoiYzVlYWM1NGNhYTQwMGEwNzI3ZTU4ZjBhP2V4cGlyZXM9MTc4NDcyMDUxOSYiLCJzaWduYXR1cmUiOiJhMDgxNGNlZTVkN2Q4ZWU4MDdiMjBmODY2YzU4NDQ5MDJmYTc0YTNlMzU1ZGU3NTgyZDFjYjBmYzg1OTU4OTFlIiwidG9vayI6MTIyOTZ9
}

response 

{
    "RequestStatus": {
        "devices": [
            {
                "brand": "Poco",
                "model": "Poco C85",
                "imeis": [
                    "860534072504571",
                    "860534072504563"
                ]
            }
        ],
        "confirmedDt": "2026-07-16T12:45:53.613315Z",
        "approvedDt": null,
        "orderCalculation": {
            "currencyAlphabeticCode": "MMK",
            "amount": 88830,
            "collectingCalculations": [
                {
                    "collectionId": 1,
                    "collectingType": "CUSTOMS_DUTY",
                    "collectionName": "Customs Duty",
                    "conditionPassed": true,
                    "amount": 12600,
                    "deviceId": 792998
                },
                {
                    "collectionId": 2,
                    "collectingType": "COMMERCIAL_TAX",
                    "collectionName": "Commercial Tax",
                    "conditionPassed": true,
                    "amount": 13230,
                    "deviceId": 792998
                },
                {
                    "collectionId": 3,
                    "collectingType": "REDEMPTION_FINE",
                    "collectionName": "Redemption Fine for non-licensed import",
                    "conditionPassed": true,
                    "amount": 63000,
                    "deviceId": 792998
                }
            ]
        },
        "declarationId": "MM-CR-51PX4FJ",
        "declarationHash": "QHostd58v97Bihz5OdzbtgAg3NFKLE_l5muH3QMX8KA",
        "basePriceSum": 252000,
        "createdDt": "2026-07-16T12:44:15.90629Z",
        "source": "LEGAL_INDIVIDUAL",
        "collectingSum": [
            {
                "collectingType": "COMMERCIAL_TAX",
                "amount": 13230
            },
            {
                "collectingType": "CUSTOMS_DUTY",
                "amount": 12600
            },
            {
                "collectingType": "REDEMPTION_FINE",
                "amount": 63000
            }
        ],
        "comment": null,
        "RegistrationType": null,
        "Method": 3,
        "StatusList": [
            {
                "Status": 3,
                "StatusChangeDateTime": "20260716T154454+0300"
            }
        ],
        "ExpirationDate": "2026-09-14T12:44:15.906325Z",
        "uniqueDeviceCount": 1,
        "releaseId": null,
        "amount": 88830.00,
        "BusinessState": "PAID"
    }
}
