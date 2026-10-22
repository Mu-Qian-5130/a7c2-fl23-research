local Logic = {}

function Logic.apply(catalog, photo, profile, lookId, observedProfile, verify)
    local before = photo:getDevelopSettings()
    before={CameraProfile=before.CameraProfile,CameraProfileDigest=before.CameraProfileDigest,Look=before.Look}
    if before.CameraProfile ~= observedProfile and before.CameraProfile ~= profile then
        return 'profile_changed_since_import'
    end
    local changed=false
    catalog:withWriteAccessDo('Apply captured A7Look profile', function()
        local current=photo:getDevelopSettings()
        if current.CameraProfile ~= before.CameraProfile then changed=true;return end
        if before.CameraProfile ~= profile then
            photo:applyDevelopSettings({ CameraProfile=profile, CameraProfileDigest='', Look={} })
        end
    end)
    if changed then return 'profile_changed_since_import' end
    -- The getter can echo an unavailable name while Adobe renders Standard.
    -- A real rendition, outside catalog write access, is the acceptance check.
    if not verify then return 'profile_requested_unverified' end
    local actual, verifyError = verify(photo)
    if actual ~= profile then
        catalog:withWriteAccessDo('Retain profile while waiting for A7Look reload', function()
            if photo:getDevelopSettings().CameraProfile == profile then
                photo:applyDevelopSettings({ CameraProfile=before.CameraProfile,
                    CameraProfileDigest=before.CameraProfileDigest or '', Look=before.Look or {} })
            end
        end)
        return verifyError and 'verification_failed' or 'awaiting_profile_reload'
    end
    if photo:getDevelopSettings().CameraProfile ~= profile then
        return 'profile_changed_since_import'
    end
    catalog:withWriteAccessDo('Record verified A7Look profile', function()
        photo:setPropertyForPlugin(_PLUGIN, 'lookId', lookId)
        photo:setPropertyForPlugin(_PLUGIN, 'sourceProfile', profile)
    end)
    return 'applied'
end

return Logic
