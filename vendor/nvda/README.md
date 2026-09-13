# NVDA Controller Client

Официалната библиотека на NV Access, през която Kapilands Таймер говори през
екранния четец NVDA — включително когато прозорецът на приложението е във фонов
режим (например докато играеш в браузъра).

| | |
|---|---|
| Файл | `x64/nvdaControllerClient.dll` (само 64-битовата версия) |
| Версия | Controller Client API 2.0, от NVDA 2025.3.3 |
| Източник | https://download.nvaccess.org/releases/2025.3.3/nvda_2025.3.3_controllerClient.zip |
| SHA256 на архива | `c619b73ae62235797b898757d04c03279f831dd11bec17271d5419d6a8050b8e` |
| SHA256 на DLL | `1da3e5c5acc004d2aa566a17f56b51f1d2da577ae6c88bbc552662be96540a1a` |
| Лиценз | GNU LGPL 2.1 — виж `license.txt` |

Библиотеката е непроменена. Лицензът позволява разпространението ѝ заедно с
приложение; промени в самата библиотека трябва да се споделят под същия лиценз.

Използвани функции: `nvdaController_testIfRunning`, `nvdaController_speakText`,
`nvdaController_brailleMessage`, `nvdaController_cancelSpeech`
(виж `kapiland/speech.py`).

Според документацията на NV Access приложението проверява дали Windows не е
заключен, преди да говори, за да не изрича данни на заключения екран.
