package bionicpro;

import com.fasterxml.jackson.databind.JsonNode;
import org.keycloak.broker.oidc.AbstractOAuth2IdentityProvider;
import org.keycloak.broker.oidc.OAuth2IdentityProviderConfig;
import org.keycloak.broker.provider.BrokeredIdentityContext;
import org.keycloak.broker.provider.IdentityBrokerException;
import org.keycloak.broker.provider.util.SimpleHttp;
import org.keycloak.broker.social.SocialIdentityProvider;
import org.keycloak.models.KeycloakSession;

public class YandexIdentityProvider extends AbstractOAuth2IdentityProvider<OAuth2IdentityProviderConfig>
        implements SocialIdentityProvider<OAuth2IdentityProviderConfig> {
    public YandexIdentityProvider(KeycloakSession session, OAuth2IdentityProviderConfig config) {
        super(session, config);
        config.setAuthorizationUrl("https://oauth.yandex.ru/authorize");
        config.setTokenUrl("https://oauth.yandex.ru/token");
    }

    @Override
    protected String getDefaultScopes() {
        return "login:info login:email";
    }

    @Override
    protected BrokeredIdentityContext doGetFederatedIdentity(String accessToken) {
        try {
            JsonNode profile = SimpleHttp.doGet("https://login.yandex.ru/info?format=json", session)
                    .header("Authorization", "OAuth " + accessToken).asJson();
            String id = getJsonProperty(profile, "id");
            if (id == null || id.isBlank()) {
                throw new IdentityBrokerException("Yandex did not return an identity");
            }
            BrokeredIdentityContext identity = new BrokeredIdentityContext(id);
            // Only the external ID is needed for the Keycloak account. Business profile
            // data is fetched separately by the BFF after explicit application consent.
            identity.setUsername("yandex-" + id);
            identity.setIdpConfig(getConfig());
            identity.setIdp(this);
            return identity;
        } catch (Exception error) {
            // Do not include provider responses/tokens in errors.
            throw new IdentityBrokerException("Cannot identify Yandex user");
        }
    }
}
