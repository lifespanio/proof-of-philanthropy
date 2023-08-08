// SPDX-License-Identifier: MIT
pragma solidity ^0.8.7;

import "openzeppelin/contracts/token/ERC721/ERC721.sol";
import "Counters.sol";
import "openzeppelin/contracts/access/Ownable.sol";
import "openzeppelin/contracts/utils/Strings.sol";
import "openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";

contract PoP is ERC721URIStorage, ERC721Enumerable, Ownable {

    string public _host = 'http://pop.lifespan.io:10443/file/nft/';

    uint256 public _limit = 999;

    using Counters for Counters.Counter;

    Counters.Counter private _tokenIds;

    constructor() public ERC721("Proof of Philanthropy", "PoP") Ownable(msg.sender) {}

    function mintNFT(address recipient)
    public 
    returns (uint256)
    {
        require(_tokenIds.current() < _limit, "All Limited Edition items attributed");
        _tokenIds.increment();

        uint256 newItemId = _tokenIds.current();

        string memory tokenURI = string.concat(_host, Strings.toString(newItemId));
        _mint(recipient, newItemId);
        _setTokenURI(newItemId, tokenURI);

        return newItemId;
    }

    function setHost(string calldata newHost)
    public onlyOwner
    {
        _host = newHost;

        for (uint256 i = 1; i < _tokenIds._value; i++) {
            string memory tokenURI = string.concat(_host, Strings.toString(i));
            _setTokenURI(i, tokenURI);
        }
    }

    function setLimit(uint256 newLimit)
    public onlyOwner
    {
        _limit = newLimit;
    }

    function tokensOfOwner(address _owner) external view returns (uint[] memory) {

        uint tokenCount = balanceOf(_owner);
        uint[] memory tokensId = new uint256[](tokenCount);

        for (uint i = 0; i < tokenCount; i++) {
            tokensId[i] = tokenOfOwnerByIndex(_owner, i);
        }
        return tokensId;
    }

    function withdraw() public payable onlyOwner {
        uint balance = address(this).balance;
        require(balance > 0, "Nothing left to withdraw");

        (bool success, ) = (msg.sender).call{value: balance}("");
        require(success, "Transfer failed.");
    }

    function tokenURI(uint256 tokenId)
    public
    view
    override(ERC721, ERC721URIStorage)
    returns (string memory) {
        return super.tokenURI(tokenId);
    }

    function supportsInterface(bytes4 interfaceId)
    public
    view
    override(ERC721Enumerable, ERC721URIStorage)
    returns (bool) {
        return super.supportsInterface(interfaceId);
    }

    function _burn(uint256 tokenId) internal override(ERC721, ERC721URIStorage) onlyOwner {
        super._burn(tokenId);
    }

    function _beforeTokenTransfer(address from, address to, uint256 firstTokenId, uint256 batchSize)
    internal
    override(ERC721, ERC721Enumerable) {
        super._beforeTokenTransfer(from, to, firstTokenId, batchSize);
    }

}
