@echo off
>>"%FAKE_BIN_LOG%" echo %*
if defined FAKE_STDOUT_FILE type "%FAKE_STDOUT_FILE%"
if defined FAKE_STDERR echo %FAKE_STDERR% 1>&2
if defined FAKE_EXIT_CODE exit /b %FAKE_EXIT_CODE%
exit /b 0
