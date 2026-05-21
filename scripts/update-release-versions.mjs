//    Substitute BackEnd - backend liaison services for SugarSubstitute and ComfyUI
//    Copyright (C) 2026  Artificial Sweetener and contributors
//
//    This program is free software: you can redistribute it and/or modify
//    it under the terms of the GNU Affero General Public License as published by
//    the Free Software Foundation, either version 3 of the License, or
//    (at your option) any later version.
//
//    This program is distributed in the hope that it will be useful,
//    but WITHOUT ANY WARRANTY; without even the implied warranty of
//    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
//    GNU Affero General Public License for more details.
//
//    You should have received a copy of the GNU Affero General Public License
//    along with this program.  If not, see <https://www.gnu.org/licenses/>.
import { readFileSync, writeFileSync } from "node:fs";

const nextVersion = process.argv[2];

if (!nextVersion) {
    throw new Error("Expected the next release version as the first argument.");
}

function writeJsonVersion(filePath) {
    const metadata = JSON.parse(readFileSync(filePath, "utf8"));
    metadata.version = nextVersion;

    if (metadata.packages?.[""]) {
        metadata.packages[""].version = nextVersion;
    }

    writeFileSync(filePath, `${JSON.stringify(metadata, null, 2)}\n`, "utf8");
}

function replaceVersionField(filePath, pattern, replacement) {
    const originalText = readFileSync(filePath, "utf8");

    if (!pattern.test(originalText)) {
        throw new Error(`Could not find a version field in ${filePath.pathname}.`);
    }

    const updatedText = originalText.replace(pattern, replacement);
    writeFileSync(filePath, updatedText, "utf8");
}

writeJsonVersion(new URL("../package.json", import.meta.url));
writeJsonVersion(new URL("../package-lock.json", import.meta.url));

replaceVersionField(
    new URL("../pyproject.toml", import.meta.url),
    /^version = "[^"]+"\r?$/m,
    `version = "${nextVersion}"`,
);

replaceVersionField(
    new URL("../substitute_backend/__init__.py", import.meta.url),
    /^__version__ = "[^"]+"\r?$/m,
    `__version__ = "${nextVersion}"`,
);
