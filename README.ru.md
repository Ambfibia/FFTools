# FFTools

FFTools - набор инструментов для Windows, чтобы создавать и применять русские патчи локализации для beta-клиента FusionFall.

Обычный рабочий процесс:

1. Выбираем исходную папку клиента, например `beta-20100104`.
2. Создаём patch-папку `beta-20100104-ru-patch`.
3. Редактируем `translation.json` и при необходимости добавляем шрифты.
4. Применяем патч и получаем сборку `beta-20100104-ru`.

## Получение репозитория

Клонировать нужно вместе с submodules:

```bat
git clone --recurse-submodules <repo-url> FFTools
cd FFTools
```

Если репозиторий уже был склонирован без submodules:

```bat
git submodule update --init --recursive
```

Используемые submodules:

- `UnityPackFF` из `https://github.com/dongresource/UnityPackFF`
- `ffbuildtool` из `https://github.com/OpenFusionProject/ffbuildtool`

## Что нужно установить

Нужны:

- Windows 10 или Windows 11.
- .NET SDK 6.0 или новее. C# инструменты таргетят `net6.0`, но собираются и новыми SDK, например .NET 8/10.
- Rust stable toolchain с `cargo`: `https://rustup.rs`.
- MSYS2 с MinGW 32-bit Python по пути `C:\msys64\mingw32\bin\python.exe`.
- Git for Windows.

Путь к Python сейчас прописан в PowerShell-скриптах:

```text
C:\msys64\mingw32\bin\python.exe
```

Если Python установлен в другом месте, поменяй `$Python` в файлах:

- `tools\build_ru_beta20100104.ps1`
- `tools\export_translation_beta20100104.ps1`

Патчинг TTF-шрифтов использует Windows GDI через Python `ctypes`, поэтому Pillow и fontTools для этого не нужны.

## Что нужно собрать

После клонирования один раз собери инструменты:

```bat
dotnet build tools\FfPatchTool\FfPatchTool.csproj -c Release
dotnet build tools\FfStringPatcher\FfStringPatcher.csproj -c Release
cargo build --manifest-path ffbuildtool\Cargo.toml
```

`30_ff_patch_tool.bat` сам соберёт `FfPatchTool`, если его нет, но лучше собрать всё заранее, чтобы сразу увидеть проблемы с окружением.

## Рекомендуемая структура папок

Лучше держать клиентские сборки в `builds`:

```text
FFTools\
  builds\
    beta-20100104\
    beta-20100104-ru-patch\
    beta-20100104-ru\
```

Папки `builds`, `work`, `logs` и корневая `fonts` игнорируются git.

Исходная папка клиента должна содержать `main.unity3d`. Файл `TableData.resourceFile` используется, когда включён экспорт и патчинг TableData.

## GUI-сценарий

Создать patch-папку:

```bat
31_create_patch_dir_gui.bat
```

Откроется окно выбора папки. Выбери исходную папку клиента, например:

```text
builds\beta-20100104
```

Инструмент создаст:

```text
builds\beta-20100104-ru-patch
```

В patch-папке будут:

- `ffpatch.json`
- `translation.json`
- опционально `font.ttf`
- опционально `fonts\*.ttf`

Применить патч:

```bat
32_apply_patch_gui.bat
```

Выбери ту же исходную папку клиента. Инструмент найдёт:

```text
builds\beta-20100104-ru-patch
```

Результат будет создан в:

```text
builds\beta-20100104-ru
```

Если папка результата уже существует, программа спросит подтверждение на перезапись.

## Шрифты

Есть два режима замены шрифтов.

Один общий fallback-шрифт:

```text
beta-20100104-ru-patch\font.ttf
```

Шрифты по семействам:

```text
beta-20100104-ru-patch\fonts\JEFFE.ttf
beta-20100104-ru-patch\fonts\ChaletBook-Regular.ttf
```

Имена файлов сопоставляются по нормализованному имени семейства:

- `JEFFE.ttf` используется для `JEFFE___14`, `JEFFE___20`, `JEFFE___40`, `JEFFE___72` и других размерных вариантов.
- `ChaletBook-Regular.ttf` используется для `ChaletBook-Regular`, `ChaletBook-Regular Small`, `ChaletBook-Regular Small 1`.

Если файла для конкретного семейства нет, инструмент попробует использовать `font.ttf`, если он есть в patch-папке.

## CLI-сценарий

Создать или обновить patch-папку:

```bat
30_ff_patch_tool.bat init --source builds\beta-20100104
```

Применить патч:

```bat
30_ff_patch_tool.bat build --source builds\beta-20100104 --force
```

Создать patch-папку и сразу собрать результат:

```bat
30_ff_patch_tool.bat make-ru --source builds\beta-20100104 --force
```

Дефолты:

- source: `beta-20100104`
- patch-папка: `beta-20100104-ru-patch`
- output-папка: `beta-20100104-ru`

Полезные параметры:

```bat
30_ff_patch_tool.bat init --source builds\beta-20100104 --font-ttf C:\Windows\Fonts\arial.ttf
30_ff_patch_tool.bat build --source builds\beta-20100104 --patch-dir builds\beta-20100104-ru-patch --output builds\beta-20100104-ru --force
30_ff_patch_tool.bat build --source builds\beta-20100104 --no-unity-assets --no-table-data --force
```

## Старые export/build wrappers

Старые батники тоже доступны:

```bat
10_export_ru_translation_beta20100104.bat
20_build_ru_beta20100104.bat -Force
```

`10_export_ru_translation_beta20100104.bat` по умолчанию экспортирует:

- только UI-строки из DLL `ldstr`;
- Unity asset строки из `main.unity3d`;
- object strings из `TableData.resourceFile`.

Полный экспорт всех DLL-строк не включается автоматически. Для него нужен флаг:

```bat
10_export_ru_translation_beta20100104.bat -AllDllStrings
```

## Что не коммитить

Не коммить сгенерированные сборки, локальные patch-результаты и артефакты сборки:

- `builds\`
- `work\`
- `logs\`
- корневую `fonts\`
- `bin\`
- `obj\`

Они уже добавлены в `.gitignore`.
